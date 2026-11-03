import json
from datetime import date, datetime, timedelta, timezone

import pytest

from emporio_agent.agent.conversation import (
    INVALID_ARGUMENTS_OUTPUT,
    TOOL_FAILED_OUTPUT,
    UNKNOWN_TOOL_OUTPUT,
    ConversationAgent,
)
from emporio_agent.agent.guardrails import (
    EMPTY_ANSWER_REPLY,
    LOCKED_OUTPUT,
    MAX_FAILED_IDENTITY_ATTEMPTS,
    MAX_TOOL_STEPS_PER_TURN,
    MAX_USER_MESSAGE_CHARS,
    MESSAGE_TOO_LONG_REPLY,
    NOT_VERIFIED_OUTPUT,
    RATE_LIMITED_REPLY,
    UNAVAILABLE_REPLY,
)
from emporio_agent.agent.history import MAX_HISTORY_MESSAGES
from emporio_agent.agent.tools import registry
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.agent.tools.registry import TOOL_SPECS
from emporio_agent.agent.tracing import ModelTrace, ToolOutcome, ToolTrace
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.conversation.messages import ChatMessage, Role
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.domain.exceptions import ChatModelError, ChatModelFailure, TraceWriteError
from emporio_agent.domain.models import OrderStatus
from emporio_agent.domain.redaction import REDACTED
from fakes import (
    FixedClock,
    InMemoryCatalogRepository,
    InMemoryOrderRepository,
    InMemoryPolicyRepository,
    RecordingErrorReporter,
    RecordingTraceSink,
    ScriptedChatModel,
    completion,
    make_category,
    make_customer,
    make_order,
    make_product,
    make_section,
    tool_call,
)

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 14, 35, tzinfo=timezone(timedelta(hours=-4)))
OWNER_PHONE = "(67) 99123-4567"
OWNER_DIGITS = "67991234567"
WRONG_PHONE = "(67) 98888-7777"
TICK_SECONDS = 0.01


class Ticker:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        self.current += TICK_SECONDS
        return self.current


@pytest.fixture
def reporter() -> RecordingErrorReporter:
    return RecordingErrorReporter()


@pytest.fixture
def rejected() -> RecordingErrorReporter:
    return RecordingErrorReporter()


@pytest.fixture
def tools(reporter, rejected) -> ToolContext:
    catalog = InMemoryCatalogRepository(
        categories=[make_category(1, "Violões")],
        products=[make_product(10, "Violão Yamaha C40", 1, "799.90")],
    )
    orders = InMemoryOrderRepository(
        orders=[make_order(1, 1, OrderStatus.SHIPPED, order_date=date(2026, 10, 30))],
        customers=[make_customer(1, OWNER_PHONE)],
    )
    policies = InMemoryPolicyRepository(
        [make_section("2", "Horário de Funcionamento", "Segunda a sexta, 9h às 18h.")]
    )
    return ToolContext(
        catalog=CatalogService(catalog),
        orders=OrderService(orders, catalog, FixedClock(TODAY)),
        policies=PolicyService(policies),
        report_error=reporter,
        report_rejected_input=rejected,
    )


def make_agent(
    model: ScriptedChatModel,
    tools: ToolContext,
    sink: RecordingTraceSink | None = None,
) -> ConversationAgent:
    return ConversationAgent(
        model=model,
        tools=tools,
        clock=FixedClock(TODAY, NOW),
        policy_index=tools.policies.index,
        trace_sink=sink,
        timer=Ticker(),
    )


def order_call(phone: str = WRONG_PHONE, call_id: str = "c1"):
    return tool_call("get_order_status", {"order_id": 1, "phone": phone}, call_id)


def tool_messages(model: ScriptedChatModel, call_index: int) -> list[ChatMessage]:
    return [m for m in model.calls[call_index].messages if m.role is Role.TOOL]


def test_plain_answer_uses_system_prompt_history_and_all_tools(tools):
    model = ScriptedChatModel([completion("Oi! Como posso ajudar?")])
    session = make_agent(model, tools).start_session()

    result = session.reply("  oi  ")

    [call] = model.calls
    assert result.text == "Oi! Como posso ajudar?"
    assert call.allow_tools is True
    assert call.tools == TOOL_SPECS
    assert call.messages[0].role is Role.SYSTEM
    assert "Lia" in call.messages[0].content
    assert "segunda-feira, 02/11/2026 14:35" in call.messages[0].content
    assert "2 Horário de Funcionamento" in call.messages[0].content
    assert call.messages[1:] == (ChatMessage(Role.USER, "  oi  "),)
    assert session.history == (
        ChatMessage(Role.USER, "  oi  "),
        ChatMessage(Role.ASSISTANT, "Oi! Como posso ajudar?"),
    )
    assert [type(step) for step in result.trace.steps] == [ModelTrace]


def test_single_tool_round_feeds_the_result_back(tools):
    call = tool_call("search_products", {"query": "yamaha"}, "fc_1")
    model = ScriptedChatModel([completion(None, call), completion("Temos o Yamaha C40!")])
    session = make_agent(model, tools).start_session()

    result = session.reply("tem violão yamaha?")

    second = model.calls[1].messages
    assert second[-2] == ChatMessage(Role.ASSISTANT, None, tool_calls=(call,))
    assert second[-1].role is Role.TOOL
    assert second[-1].tool_call_id == "fc_1"
    assert json.loads(second[-1].content)["items"][0]["name"] == "Violão Yamaha C40"
    assert result.text == "Temos o Yamaha C40!"
    model_step, tool_step, final_step = result.trace.steps
    assert isinstance(model_step, ModelTrace)
    assert isinstance(final_step, ModelTrace)
    assert tool_step == ToolTrace(
        name="search_products",
        arguments={"query": "yamaha"},
        duration_ms=10,
        outcome=ToolOutcome.OK,
        output_chars=len(second[-1].content),
    )
    assert len(session.history) == 4


def test_multiple_tool_calls_run_sequentially_in_order(tools):
    calls = (
        tool_call("list_categories", "{}", "a"),
        tool_call("search_products", {"query": "yamaha"}, "b"),
        tool_call("get_policy_sections", {"section_ids": ["2"]}, "c"),
    )
    model = ScriptedChatModel([completion(None, *calls), completion("Pronto")])

    result = make_agent(model, tools).start_session().reply("me ajuda")

    results = tool_messages(model, 1)
    assert [message.tool_call_id for message in results] == ["a", "b", "c"]
    assert "Violões" in results[0].content
    assert "Horário de Funcionamento" in results[2].content
    assert [step.name for step in result.trace.tool_steps] == [
        "list_categories",
        "search_products",
        "get_policy_sections",
    ]


def test_unknown_tool_returns_an_error_and_the_loop_continues(tools):
    model = ScriptedChatModel(
        [completion(None, tool_call("delete_everything")), completion("Posso ajudar?")]
    )

    result = make_agent(model, tools).start_session().reply("oi")

    assert tool_messages(model, 1)[0].content == UNKNOWN_TOOL_OUTPUT == '{"error":"unknown_tool"}'
    assert result.trace.tool_steps[0].outcome is ToolOutcome.REJECTED
    assert result.text == "Posso ajudar?"


@pytest.mark.parametrize("arguments", ["not json", "[1, 2]", '"texto"', "{"])
def test_invalid_json_arguments_return_invalid_arguments(tools, rejected, arguments):
    model = ScriptedChatModel(
        [completion(None, tool_call("search_products", arguments)), completion("Ok")]
    )

    result = make_agent(model, tools).start_session().reply("oi")

    assert tool_messages(model, 1)[0].content == INVALID_ARGUMENTS_OUTPUT
    assert INVALID_ARGUMENTS_OUTPUT == '{"error":"invalid_arguments"}'
    assert result.trace.tool_steps[0].outcome is ToolOutcome.REJECTED
    assert [scope for scope, _ in rejected.reports] == ["agent.tools.search_products"]


def test_empty_arguments_are_treated_as_an_empty_object(tools):
    model = ScriptedChatModel(
        [completion(None, tool_call("list_categories", "")), completion("Ok")]
    )

    result = make_agent(model, tools).start_session().reply("categorias?")

    assert result.trace.tool_steps[0].outcome is ToolOutcome.OK


def test_schema_rejections_are_traced_as_rejected(tools, rejected):
    model = ScriptedChatModel(
        [completion(None, tool_call("search_products", {"limit": "muitos"})), completion("Ok")]
    )

    result = make_agent(model, tools).start_session().reply("oi")

    assert result.trace.tool_steps[0].outcome is ToolOutcome.REJECTED
    assert [scope for scope, _ in rejected.reports] == ["tools.search_products"]


def test_handler_exception_is_reported_and_answered_as_tool_failed(tools, reporter, monkeypatch):
    def broken_handler(context, arguments):
        raise RuntimeError("falha inesperada")

    monkeypatch.setitem(registry.TOOL_HANDLERS, "list_categories", broken_handler)
    model = ScriptedChatModel([completion(None, tool_call("list_categories")), completion("Ops")])

    result = make_agent(model, tools).start_session().reply("categorias?")

    assert tool_messages(model, 1)[0].content == TOOL_FAILED_OUTPUT == '{"error":"tool_failed"}'
    assert result.trace.tool_steps[0].outcome is ToolOutcome.ERROR
    [(scope, error)] = reporter.reports
    assert scope == "agent.tools.list_categories"
    assert isinstance(error, RuntimeError)


def test_step_cap_forces_a_final_answer_without_tools(tools):
    looping = [
        completion(None, tool_call("list_categories", "{}", f"c{index}"))
        for index in range(MAX_TOOL_STEPS_PER_TURN)
    ]
    model = ScriptedChatModel([*looping, completion("Resumo final")])

    result = make_agent(model, tools).start_session().reply("oi")

    assert [call.allow_tools for call in model.calls] == [True] * MAX_TOOL_STEPS_PER_TURN + [False]
    assert len(result.trace.tool_steps) == MAX_TOOL_STEPS_PER_TURN
    assert result.text == "Resumo final"


def test_tool_calls_after_the_cap_are_ignored(tools):
    looping = [
        completion(None, tool_call("list_categories", "{}", f"c{index}"))
        for index in range(MAX_TOOL_STEPS_PER_TURN + 1)
    ]
    model = ScriptedChatModel(looping)

    result = make_agent(model, tools).start_session().reply("oi")

    assert len(model.calls) == MAX_TOOL_STEPS_PER_TURN + 1
    assert len(result.trace.tool_steps) == MAX_TOOL_STEPS_PER_TURN
    assert result.text == EMPTY_ANSWER_REPLY


@pytest.mark.parametrize("content", [None, "", "   \n"])
def test_empty_final_answer_uses_the_fallback(tools, content):
    session = make_agent(ScriptedChatModel([completion(content)]), tools).start_session()

    result = session.reply("oi")

    assert result.text == EMPTY_ANSWER_REPLY
    assert session.history[-1] == ChatMessage(Role.ASSISTANT, EMPTY_ANSWER_REPLY)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (ChatModelFailure.RATE_LIMITED, RATE_LIMITED_REPLY),
        (ChatModelFailure.UNAVAILABLE, UNAVAILABLE_REPLY),
        (ChatModelFailure.TIMEOUT, UNAVAILABLE_REPLY),
        (ChatModelFailure.AUTHENTICATION, UNAVAILABLE_REPLY),
        (ChatModelFailure.INVALID_RESPONSE, UNAVAILABLE_REPLY),
    ],
)
def test_chat_model_errors_become_fixed_messages(tools, reason, expected):
    session = make_agent(ScriptedChatModel([ChatModelError(reason)]), tools).start_session()

    result = session.reply("oi")

    assert result.text == expected
    assert session.history == (ChatMessage(Role.USER, "oi"),)


def test_fixed_failure_messages_are_customer_friendly():
    assert "instantes" in RATE_LIMITED_REPLY
    assert "(67) 3341-4444" in UNAVAILABLE_REPLY
    assert "instabilidade" in UNAVAILABLE_REPLY


def test_failure_mid_turn_keeps_only_the_user_message(tools):
    model = ScriptedChatModel(
        [
            completion(None, tool_call("list_categories")),
            ChatModelError(ChatModelFailure.TIMEOUT),
            completion("Agora sim"),
        ]
    )
    session = make_agent(model, tools).start_session()

    session.reply("primeira")
    result = session.reply("segunda")

    assert result.text == "Agora sim"
    assert model.calls[2].messages[1:] == (
        ChatMessage(Role.USER, "primeira"),
        ChatMessage(Role.USER, "segunda"),
    )


def test_too_long_message_is_answered_without_calling_the_model(tools):
    model = ScriptedChatModel([completion("ok")])
    session = make_agent(model, tools).start_session()

    result = session.reply("x" * (MAX_USER_MESSAGE_CHARS + 1))

    assert result.text == MESSAGE_TOO_LONG_REPLY
    assert model.calls == []
    assert session.history == ()
    assert session.reply("x" * MAX_USER_MESSAGE_CHARS).text == "ok"


def test_identity_lockout_after_three_failures_blocks_order_tools(tools):
    failures = [order_call(call_id=f"f{index}") for index in range(MAX_FAILED_IDENTITY_ATTEMPTS)]
    blocked_return = tool_call(
        "assess_return_eligibility",
        {"order_id": 1, "phone": OWNER_PHONE, "reason": "regret"},
        "blocked_return",
    )
    model = ScriptedChatModel(
        [
            completion(None, order_call(OWNER_PHONE, "ok"), *failures),
            completion(
                None,
                order_call(OWNER_PHONE, "blocked"),
                blocked_return,
                tool_call("list_categories", "{}", "still_ok"),
            ),
            completion("Vou encaminhar para a equipe."),
        ]
    )

    result = make_agent(model, tools).start_session().reply("meu pedido")

    outputs = [message.content for message in tool_messages(model, len(model.calls) - 1)]
    assert json.loads(outputs[0])["verified"] is True
    assert outputs[1:4] == [NOT_VERIFIED_OUTPUT] * MAX_FAILED_IDENTITY_ATTEMPTS
    assert outputs[4] == outputs[5] == LOCKED_OUTPUT == '{"verified":false,"locked":true}'
    assert "Violões" in outputs[6]
    assert [step.outcome for step in result.trace.tool_steps][4:6] == [ToolOutcome.LOCKED] * 2


def test_lockout_persists_across_turns_but_not_sessions(tools):
    model = ScriptedChatModel(
        [
            *[
                response
                for index in range(MAX_FAILED_IDENTITY_ATTEMPTS)
                for response in (
                    completion(None, order_call(call_id=f"f{index}")),
                    completion("Não"),
                )
            ],
            completion(None, order_call(OWNER_PHONE, "late")),
            completion("Bloqueado"),
            completion(None, order_call(OWNER_PHONE, "fresh")),
            completion("Achei"),
        ]
    )
    agent = make_agent(model, tools)
    session = agent.start_session()
    for _ in range(MAX_FAILED_IDENTITY_ATTEMPTS):
        session.reply("pedido 1")

    session.reply("tenta de novo")
    fresh = agent.start_session()
    fresh.reply("pedido 1")

    assert tool_messages(model, 7)[-1].content == LOCKED_OUTPUT
    assert json.loads(tool_messages(model, 9)[-1].content)["verified"] is True
    assert fresh.session_id != session.session_id


def test_history_window_is_bounded_and_never_starts_with_a_tool_message(tools):
    responses = []
    for index in range(20):
        responses.append(completion(None, tool_call("list_categories", "{}", f"c{index}")))
        responses.append(completion(f"resposta {index}"))
    model = ScriptedChatModel(responses)
    session = make_agent(model, tools).start_session()

    for index in range(20):
        session.reply(f"pergunta {index}")

    for call in model.calls:
        window = call.messages[1:]
        assert len(window) <= MAX_HISTORY_MESSAGES
        assert window[0].role is not Role.TOOL
        for position, message in enumerate(window):
            if message.role is Role.TOOL:
                previous = window[position - 1]
                assert previous.role is Role.ASSISTANT and previous.tool_calls
    assert model.calls[-1].messages[0].role is Role.SYSTEM


def test_trace_redacts_phone_like_values_everywhere(tools):
    calls = (
        order_call(OWNER_PHONE, "a"),
        tool_call("get_order_status", {"order_id": 1, "contato": OWNER_DIGITS}, "b"),
        tool_call("get_order_status", {"order_id": 1, "dados": [int(OWNER_DIGITS)]}, "c"),
        tool_call(f"tool_{OWNER_DIGITS}", "{}", "d"),
    )
    sink = RecordingTraceSink()
    model = ScriptedChatModel([completion(None, *calls), completion("Ok")])

    result = make_agent(model, tools, sink).start_session().reply(f"meu fone {OWNER_PHONE}")

    first, second, third, fourth = result.trace.tool_steps
    assert first.arguments == {"order_id": 1, "phone": REDACTED}
    assert second.arguments == {"order_id": 1, "contato": REDACTED}
    assert third.arguments == {"order_id": 1, "dados": [REDACTED]}
    assert OWNER_DIGITS not in fourth.name
    serialized = json.dumps(sink.records, ensure_ascii=False)
    for value in (OWNER_PHONE, OWNER_DIGITS, "meu fone"):
        assert value not in serialized


def test_trace_sink_receives_one_record_per_turn(tools):
    sink = RecordingTraceSink()
    model = ScriptedChatModel(
        [
            completion(None, tool_call("list_categories"), prompt_tokens=200, completion_tokens=20),
            completion("Temos violões", prompt_tokens=300, completion_tokens=30, retries=2),
            completion("De nada"),
        ]
    )
    session = make_agent(model, tools, sink).start_session()

    session.reply("categorias?")
    session.reply("obrigado")

    first, second = sink.records
    assert first["session_id"] == second["session_id"] == session.session_id
    assert [first["turn"], second["turn"]] == [1, 2]
    assert first["prompt_tokens"] == 500
    assert first["completion_tokens"] == 50
    assert first["retries"] == 2
    assert [step["kind"] for step in first["steps"]] == ["model", "tool", "model"]
    assert first["steps"][1]["outcome"] == "ok"
    assert "Temos violões" not in json.dumps(sink.records, ensure_ascii=False)


def test_trace_sink_failure_is_reported_without_breaking_the_reply(tools, reporter):
    class BrokenSink:
        def write(self, record):
            raise TraceWriteError("disco cheio")

    agent = ConversationAgent(
        model=ScriptedChatModel([completion("Oi")]),
        tools=tools,
        clock=FixedClock(TODAY, NOW),
        policy_index=tools.policies.index,
        trace_sink=BrokenSink(),
    )

    assert agent.start_session().reply("oi").text == "Oi"
    assert [scope for scope, _ in reporter.reports] == ["agent.trace"]


def test_turn_totals_sum_model_steps(tools):
    model = ScriptedChatModel(
        [
            completion(None, tool_call("list_categories"), prompt_tokens=10, completion_tokens=1),
            completion("Ok", prompt_tokens=20, completion_tokens=2, retries=1),
        ]
    )

    trace = make_agent(model, tools).start_session().reply("oi").trace

    assert (trace.prompt_tokens, trace.completion_tokens, trace.retries) == (30, 3, 1)
    assert trace.duration_ms == 30
