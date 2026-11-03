from datetime import date, datetime, timedelta, timezone

import pytest

from emporio_agent.agent.conversation import ConversationAgent
from emporio_agent.agent.guardrails import RATE_LIMITED_REPLY
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.domain.exceptions import ChatModelError, ChatModelFailure
from emporio_agent.domain.models import OrderStatus
from emporio_agent.domain.redaction import REDACTED
from emporio_agent.evaluation.cases import EvalCase, EvalTurn, TurnExpectation
from emporio_agent.evaluation.checks import CUSTOMER_PHONE_REASON
from emporio_agent.evaluation.resolver import EvalDataResolver
from emporio_agent.evaluation.runner import MODEL_ERROR_REASON, EvalRunner
from fakes import (
    FixedClock,
    InMemoryCatalogRepository,
    InMemoryOrderRepository,
    InMemoryPolicyRepository,
    RecordingErrorReporter,
    ScriptedChatModel,
    completion,
    make_category,
    make_customer,
    make_order,
    make_product,
    tool_call,
)

TODAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone(timedelta(hours=-4)))
OWNER_PHONE = "(11) 97777-1212"
PAUSE_SECONDS = 15.0


class StepTimer:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        self.current += 0.25
        return self.current


class CountingAgent:
    def __init__(self, agent: ConversationAgent) -> None:
        self._agent = agent
        self.sessions = 0

    def start_session(self):
        self.sessions += 1
        return self._agent.start_session()


@pytest.fixture
def orders() -> InMemoryOrderRepository:
    return InMemoryOrderRepository(
        orders=[make_order(1, 1, OrderStatus.DELIVERED, order_date=date(2026, 10, 1))],
        customers=[make_customer(1, OWNER_PHONE, name="Joana Prado")],
    )


@pytest.fixture
def tools(orders) -> ToolContext:
    catalog = InMemoryCatalogRepository(
        categories=[make_category(1, "Violões")],
        products=[make_product(10, "Violão Yamaha C40", 1, "799.90")],
    )
    return ToolContext(
        catalog=CatalogService(catalog),
        orders=OrderService(orders, catalog, FixedClock(TODAY)),
        policies=PolicyService(InMemoryPolicyRepository()),
        report_error=RecordingErrorReporter(),
        report_rejected_input=RecordingErrorReporter(),
    )


@pytest.fixture
def resolver(orders) -> EvalDataResolver:
    return EvalDataResolver(orders, orders.customers)


def make_agent(model: ScriptedChatModel, tools: ToolContext) -> CountingAgent:
    return CountingAgent(
        ConversationAgent(
            model=model,
            tools=tools,
            clock=FixedClock(TODAY, NOW),
            policy_index=tools.policies.index,
        )
    )


def make_runner(agent, resolver, sleeps: list[float], pause: float = PAUSE_SECONDS):
    return EvalRunner(agent, resolver, pause, sleeps.append, timer=StepTimer())


def single_turn_case(case_id: str, user: str, expect: TurnExpectation) -> EvalCase:
    return EvalCase(case_id, "catalog", "descrição", (EvalTurn(user, expect),))


def test_passing_turn_records_tools_tokens_models_and_duration(tools, resolver):
    model = ScriptedChatModel(
        [
            completion(None, tool_call("get_product", {"product_id": 10}), model="m-main"),
            completion("O Violão Yamaha C40 sai por R$ 799,90.", model="m-backup", retries=2),
        ]
    )
    expect = TurnExpectation(tools_all=("get_product",), contains_all=("799,90",))

    (record,) = make_runner(make_agent(model, tools), resolver, []).run(
        [single_turn_case("price", "quanto custa o c40?", expect)]
    )

    (turn,) = record.turns
    assert record.passed and turn.passed
    assert turn.reasons == ()
    assert turn.tool_names == ("get_product",)
    assert turn.tools[0].arguments == {"product_id": 10}
    assert turn.tools[0].outcome == "ok"
    assert turn.models == ("m-main", "m-backup")
    assert (turn.prompt_tokens, turn.completion_tokens, turn.retries) == (200, 20, 2)
    assert turn.duration_ms == 250
    assert turn.has_tool_expectations and turn.tools_passed
    assert turn.reply == "O Violão Yamaha C40 sai por R$ 799,90."


def test_failing_turn_lists_tool_and_text_reasons(tools, resolver):
    model = ScriptedChatModel([completion("Não sei o preço.")])
    expect = TurnExpectation(tools_any=("get_product",), contains_all=("799,90",))

    (record,) = make_runner(make_agent(model, tools), resolver, []).run(
        [single_turn_case("price", "quanto custa?", expect)]
    )

    assert not record.passed
    assert record.turns[0].reasons == (
        "expected any of tools ['get_product']",
        "missing text '799,90'",
    )
    assert not record.turns[0].tools_passed
    assert record.reasons == (
        "turn 1: expected any of tools ['get_product']",
        "turn 1: missing text '799,90'",
    )


def test_placeholders_are_resolved_for_the_agent_but_not_recorded(tools, resolver):
    model = ScriptedChatModel(
        [
            completion(None, tool_call("get_order_status", {"order_id": 1, "phone": OWNER_PHONE})),
            completion(f"Joana, seu pedido foi entregue. Telefone {OWNER_PHONE} confere."),
        ]
    )
    case = single_turn_case(
        "order", "pedido 1, tel {phone:order_1}", TurnExpectation(tools_all=("get_order_status",))
    )

    (record,) = make_runner(make_agent(model, tools), resolver, []).run([case])

    (turn,) = record.turns
    assert OWNER_PHONE in model.calls[0].messages[-1].content
    assert turn.user == "pedido 1, tel {phone:order_1}"
    assert turn.tools[0].arguments == {"order_id": 1, "phone": REDACTED}
    assert turn.reasons == (CUSTOMER_PHONE_REASON,)
    assert OWNER_PHONE not in turn.reply
    assert REDACTED in turn.reply


def test_pii_check_can_be_disabled_per_turn(tools, resolver):
    model = ScriptedChatModel([completion(f"Anotei o {OWNER_PHONE}.")])
    case = single_turn_case("pii", "oi", TurnExpectation(no_customer_pii=False))

    (record,) = make_runner(make_agent(model, tools), resolver, []).run([case])

    assert record.passed


def test_model_error_fails_the_turn_without_stopping_the_run(tools, resolver):
    model = ScriptedChatModel(
        [
            ChatModelError(ChatModelFailure.RATE_LIMITED),
            completion("Oi de novo!"),
            completion("Tudo certo."),
        ]
    )
    first = EvalCase(
        "flaky",
        "policy",
        "d",
        (
            EvalTurn("oi", TurnExpectation(contains_all=("nunca",))),
            EvalTurn("oi?", TurnExpectation(contains_all=("de novo",))),
        ),
    )
    second = single_turn_case("next", "e ai", TurnExpectation(contains_any=("certo",)))

    records = make_runner(make_agent(model, tools), resolver, []).run([first, second])

    failed_turn, recovered_turn = records[0].turns
    assert failed_turn.reasons == (MODEL_ERROR_REASON,)
    assert failed_turn.model_error
    assert failed_turn.reply == RATE_LIMITED_REPLY
    assert recovered_turn.passed and not recovered_turn.model_error
    assert not records[0].passed
    assert records[1].passed


def test_sleeps_between_turns_but_not_after_the_last(tools, resolver):
    model = ScriptedChatModel([completion("a"), completion("b"), completion("c")])
    two_turns = EvalCase(
        "two", "policy", "d", (EvalTurn("1", TurnExpectation()), EvalTurn("2", TurnExpectation()))
    )
    sleeps: list[float] = []

    make_runner(make_agent(model, tools), resolver, sleeps).run(
        [two_turns, single_turn_case("one", "3", TurnExpectation())]
    )

    assert sleeps == [PAUSE_SECONDS, PAUSE_SECONDS]


def test_zero_pause_never_sleeps(tools, resolver):
    model = ScriptedChatModel([completion("a"), completion("b")])
    sleeps: list[float] = []
    cases = [
        single_turn_case("a", "1", TurnExpectation()),
        single_turn_case("b", "2", TurnExpectation()),
    ]

    make_runner(make_agent(model, tools), resolver, sleeps, pause=0).run(cases)

    assert sleeps == []


def test_every_case_runs_in_a_fresh_session(tools, resolver):
    model = ScriptedChatModel([completion("a"), completion("b"), completion("c")])
    first = EvalCase(
        "first", "policy", "d", (EvalTurn("1", TurnExpectation()), EvalTurn("2", TurnExpectation()))
    )
    agent = make_agent(model, tools)

    make_runner(agent, resolver, []).run(
        [first, single_turn_case("second", "3", TurnExpectation())]
    )

    assert agent.sessions == 2
    assert [len(call.messages) for call in model.calls] == [2, 4, 2]


def test_observer_receives_each_case_record(tools, resolver):
    model = ScriptedChatModel([completion("a"), completion("b")])
    seen = []
    runner = EvalRunner(make_agent(model, tools), resolver, 0, lambda _: None, on_case=seen.append)

    records = runner.run(
        [
            single_turn_case("a", "1", TurnExpectation()),
            single_turn_case("b", "2", TurnExpectation()),
        ]
    )

    assert tuple(seen) == records
