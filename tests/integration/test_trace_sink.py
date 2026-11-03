import json
from datetime import date

import pytest

from emporio_agent.agent.conversation import ConversationAgent
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.domain.exceptions import TraceWriteError
from emporio_agent.infrastructure.observability.logging import log_error, log_warning
from emporio_agent.infrastructure.observability.trace_sink import TRACE_FILE_NAME, JsonlTraceSink
from fakes import FixedClock, ScriptedChatModel, completion, tool_call


def phone_of(repository, order_id: int) -> str:
    return repository.get_customer(repository.get_order(order_id).customer_id).phone


def test_sink_appends_one_json_line_per_record(tmp_path):
    sink = JsonlTraceSink(tmp_path / "traces")

    sink.write({"turn": 1, "texto": "ação"})
    sink.write({"turn": 2})

    lines = (tmp_path / "traces" / TRACE_FILE_NAME).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"turn": 1, "texto": "ação"}, {"turn": 2}]


def test_sink_raises_a_domain_error_when_the_path_is_unusable(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x", encoding="utf-8")

    with pytest.raises(TraceWriteError):
        JsonlTraceSink(blocker).write({"turn": 1})


def test_real_conversation_trace_never_contains_the_phone(tmp_path, repository, container):
    phone = phone_of(repository, 1)
    digits = "".join(char for char in phone if char.isdigit())
    tools = ToolContext(
        catalog=CatalogService(repository),
        orders=OrderService(repository, repository, FixedClock(date(2026, 3, 1))),
        policies=container.policy_service,
        report_error=log_error,
        report_rejected_input=log_warning,
    )
    calls = (
        tool_call("get_order_status", {"order_id": 1, "phone": phone}, "a"),
        tool_call("get_order_status", {"order_id": 1, "telefone_cliente": digits}, "b"),
        tool_call("search_products", {"query": f"violão {phone}"}, "c"),
    )
    model = ScriptedChatModel([completion(None, *calls), completion("Seu pedido foi entregue.")])
    agent = ConversationAgent(
        model=model,
        tools=tools,
        clock=FixedClock(date(2026, 3, 1)),
        policy_index=container.policy_service.index,
        trace_sink=JsonlTraceSink(tmp_path),
    )

    agent.start_session().reply(f"pedido 1, telefone {phone}")

    content = (tmp_path / TRACE_FILE_NAME).read_text(encoding="utf-8")
    record = json.loads(content)
    assert [step["name"] for step in record["steps"] if step["kind"] == "tool"] == [
        "get_order_status",
        "get_order_status",
        "search_products",
    ]
    for value in (phone, digits, digits[2:], "Seu pedido", "pedido 1, telefone"):
        assert value not in content
