import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from emporio_agent.agent.conversation import TurnResult
from emporio_agent.agent.tracing import ModelTrace, TurnTrace
from emporio_agent.config import Settings
from emporio_agent.evaluation.cli import (
    DEFAULT_CASES_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAUSE_SECONDS,
    EXIT_FAILURE,
    EXIT_MISSING_API_KEY,
    EXIT_OK,
    JSON_REPORT_NAME,
    MARKDOWN_REPORT_NAME,
    MISSING_KEY_MESSAGE,
    EvalDependencies,
    EvalOptions,
    main,
    parse_options,
    run_evaluation,
)
from emporio_agent.evaluation.resolver import EvalDataResolver
from fakes import InMemoryOrderRepository, RecordingErrorReporter, make_customer, make_order

NOW = datetime(2026, 11, 3, 9, 30, tzinfo=timezone(timedelta(hours=-4)))
OWNER_PHONE = "(11) 97777-1212"
CASES_DOCUMENT = {
    "cases": [
        {
            "id": "price",
            "category": "catalog",
            "description": "preço",
            "turns": [{"user": "quanto custa?", "expect": {"contains_all": ["R$ 10"]}}],
        },
        {
            "id": "hours",
            "category": "policy",
            "description": "horário",
            "turns": [
                {"user": "abre domingo?", "expect": {"contains_any": ["fechado"]}},
                {"user": "e sabado?"},
            ],
        },
        {
            "id": "order",
            "category": "orders",
            "description": "pedido",
            "turns": [{"user": "pedido 1 tel {phone:order_1}"}],
        },
    ]
}


class EchoSession:
    def __init__(self, received: list[str]) -> None:
        self._received = received

    def reply(self, user_text: str) -> TurnResult:
        self._received.append(user_text)
        trace = TurnTrace((ModelTrace("modelo-a", 500, 20, 300, 0),))
        return TurnResult(text="Custa R$ 10. Domingo fechado.", trace=trace)


class EchoAgent:
    def __init__(self) -> None:
        self.received: list[str] = []

    def start_session(self) -> EchoSession:
        return EchoSession(self.received)


def write_cases(tmp_path: Path, document: object = CASES_DOCUMENT) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def dependencies(agent: EchoAgent, reporter: RecordingErrorReporter | None = None):
    orders = InMemoryOrderRepository(
        orders=[make_order(1, 1)], customers=[make_customer(1, OWNER_PHONE)]
    )
    return EvalDependencies(
        agent=agent,
        resolver=EvalDataResolver(orders, orders.customers),
        report_error=RecordingErrorReporter() if reporter is None else reporter,
        primary_model="modelo-a",
        now=lambda: NOW,
    )


def evaluate(tmp_path: Path, *argv: str, agent: EchoAgent | None = None, cases=None):
    cases_path = write_cases(tmp_path) if cases is None else cases
    options = parse_options(["--cases", str(cases_path), "--out", str(tmp_path / "out"), *argv])
    output, errors, sleeps = io.StringIO(), io.StringIO(), []
    code = run_evaluation(
        options, dependencies(agent or EchoAgent()), output, errors, sleeps.append
    )
    return code, output.getvalue(), errors.getvalue(), sleeps


def test_parse_options_defaults():
    assert parse_options([]) == EvalOptions(
        cases=DEFAULT_CASES_PATH,
        only=(),
        category=None,
        pause=DEFAULT_PAUSE_SECONDS,
        out=DEFAULT_OUTPUT_DIR,
    )


def test_parse_options_splits_ids_and_clamps_pause():
    options = parse_options(["--only", " a, b,,c ", "--category", "policy", "--pause", "-3"])

    assert options.only == ("a", "b", "c")
    assert options.category == "policy"
    assert options.pause == 0.0


def test_full_run_writes_reports_and_prints_one_summary_line(tmp_path):
    agent = EchoAgent()

    code, output, errors, sleeps = evaluate(tmp_path, "--pause", "5", agent=agent)

    assert code == EXIT_OK
    assert len(output.splitlines()) == 1
    assert output.startswith("eval: cases 100.0% (3/3), turns 100.0% (4/4)")
    assert errors.splitlines() == ["[1/3] price PASS", "[2/3] hours PASS", "[3/3] order PASS"]
    assert sleeps == [5.0, 5.0, 5.0]
    assert agent.received[-1] == f"pedido 1 tel {OWNER_PHONE}"
    markdown = (tmp_path / "out" / MARKDOWN_REPORT_NAME).read_text(encoding="utf-8")
    report = json.loads((tmp_path / "out" / JSON_REPORT_NAME).read_text(encoding="utf-8"))
    assert "- Date: 2026-11-03 09:30 (store time)" in markdown
    assert [case["id"] for case in report["cases"]] == ["price", "hours", "order"]
    assert "97777" not in markdown and "97777" not in json.dumps(report)


def test_failures_are_data_and_still_exit_zero(tmp_path):
    document = {
        "cases": [
            {
                "id": "x",
                "category": "catalog",
                "description": "d",
                "turns": [{"user": "oi", "expect": {"contains_all": ["nunca dito"]}}],
            }
        ]
    }

    code, output, errors, _ = evaluate(tmp_path, cases=write_cases(tmp_path, document))

    assert code == EXIT_OK
    assert output.startswith("eval: cases 0.0% (0/1)")
    assert errors == "[1/1] x FAIL\n"


def test_only_filter_runs_the_listed_cases(tmp_path):
    agent = EchoAgent()

    code, _, errors, sleeps = evaluate(tmp_path, "--only", "order,price", agent=agent)

    assert code == EXIT_OK
    assert errors.splitlines() == ["[1/2] price PASS", "[2/2] order PASS"]
    assert len(agent.received) == 2
    assert sleeps == [DEFAULT_PAUSE_SECONDS]


def test_category_filter_runs_only_that_category(tmp_path):
    code, _, errors, _ = evaluate(tmp_path, "--category", "policy", "--pause", "0")

    assert code == EXIT_OK
    assert errors.splitlines() == ["[1/1] hours PASS"]


@pytest.mark.parametrize(
    "argv",
    [("--only", "price,missing"), ("--category", "nenhuma")],
)
def test_bad_selection_exits_with_one(tmp_path, argv):
    code, output, errors, _ = evaluate(tmp_path, *argv)

    assert code == EXIT_FAILURE
    assert output == ""
    assert errors.startswith("Invalid evaluation cases:")


def test_unresolvable_placeholder_exits_with_one_before_calling_the_model(tmp_path):
    document = {
        "cases": [
            {
                "id": "x",
                "category": "orders",
                "description": "d",
                "turns": [{"user": "tel {phone:order_404}"}],
            }
        ]
    }
    agent = EchoAgent()

    code, _, errors, _ = evaluate(tmp_path, agent=agent, cases=write_cases(tmp_path, document))

    assert code == EXIT_FAILURE
    assert "unknown order" in errors
    assert agent.received == []


def test_unwritable_output_exits_with_one(tmp_path):
    blocker = tmp_path / "out"
    blocker.write_text("não é pasta", encoding="utf-8")

    code, output, errors, _ = evaluate(tmp_path)

    assert code == EXIT_FAILURE
    assert output == ""
    assert "Could not write the reports" in errors


def test_main_without_api_key_exits_with_two(monkeypatch, data_dir):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("EMPORIO_GROQ_API_KEY", raising=False)
    errors = io.StringIO()

    code = main([], settings=Settings(_env_file=None, data_dir=data_dir), errors=errors)

    assert code == EXIT_MISSING_API_KEY
    assert errors.getvalue() == f"{MISSING_KEY_MESSAGE}\n"


@pytest.mark.parametrize("content", ["{ quebrado", json.dumps({"cases": []})])
def test_main_with_bad_cases_file_exits_with_one(tmp_path, data_dir, content):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(content, encoding="utf-8")
    errors = io.StringIO()

    code = main(
        ["--cases", str(cases_path), "--out", str(tmp_path / "out")],
        settings=Settings(_env_file=None, data_dir=data_dir, groq_api_key="gsk_falsa"),
        output=io.StringIO(),
        errors=errors,
    )

    assert code == EXIT_FAILURE
    assert errors.getvalue().startswith("Invalid evaluation cases:")
    assert not (tmp_path / "out").exists()


def test_main_with_missing_data_exits_with_one(tmp_path):
    code = main(
        [],
        settings=Settings(_env_file=None, data_dir=tmp_path / "nada", groq_api_key="gsk_falsa"),
        output=io.StringIO(),
        errors=io.StringIO(),
    )

    assert code == EXIT_FAILURE
