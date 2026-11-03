import json
from datetime import datetime, timedelta, timezone

from emporio_agent.domain.redaction import REDACTED
from emporio_agent.evaluation.report import (
    percentile,
    render_json,
    render_markdown,
    summarize,
    summary_line,
)
from emporio_agent.evaluation.runner import CaseRecord, ToolCallRecord, TurnRecord

GENERATED_AT = datetime(2026, 11, 3, 14, 5, tzinfo=timezone(timedelta(hours=-4)))
PRIMARY = "openai/gpt-oss-120b"
FALLBACK = "openai/gpt-oss-20b"
CUSTOMER_PHONE = "(11) 97777-1212"
CUSTOMER_DIGITS = ("97777", "1212", "11977771212")


def turn(
    *,
    reasons=(),
    tools=(),
    models=(PRIMARY,),
    duration_ms=1000,
    has_tool_expectations=False,
    tools_passed=True,
    model_error=False,
    reply="Oi!",
    user="oi",
) -> TurnRecord:
    return TurnRecord(
        user=user,
        reply=reply,
        tools=tuple(tools),
        prompt_tokens=1000,
        completion_tokens=50,
        models=tuple(models),
        retries=1 if model_error else 0,
        duration_ms=duration_ms,
        reasons=tuple(reasons),
        has_tool_expectations=has_tool_expectations,
        tools_passed=tools_passed,
        model_error=model_error,
    )


ORDER_TOOL = ToolCallRecord("get_order_status", {"order_id": 1, "phone": REDACTED}, "ok")
CASES = (
    CaseRecord(
        "orders_ok",
        "orders",
        "Pedido com telefone",
        (
            turn(
                tools=[ORDER_TOOL],
                has_tool_expectations=True,
                user="pedido 1, tel {phone:order_1}",
                reply=f"Pedido entregue! Equipe: (67) 3341-4444. Seu tel {REDACTED}.",
                duration_ms=800,
            ),
        ),
    ),
    CaseRecord(
        "orders_bad",
        "orders",
        "Telefone errado",
        (
            turn(
                reasons=["missing tools ['get_order_status']", "missing text 'a|b'"],
                has_tool_expectations=True,
                tools_passed=False,
                models=(PRIMARY, FALLBACK),
                duration_ms=3000,
            ),
        ),
    ),
    CaseRecord(
        "policy_flaky",
        "policy",
        "Domingo",
        (
            turn(reasons=["model_error"], model_error=True, models=(), duration_ms=200),
            turn(duration_ms=1200),
        ),
    ),
)
SUMMARY = summarize(CASES, PRIMARY, GENERATED_AT)


def test_percentile_uses_nearest_rank():
    assert percentile([], 50) == 0
    assert percentile([5], 95) == 5
    assert percentile([100, 300, 200, 400], 50) == 200
    assert percentile(list(range(1, 101)), 95) == 95


def test_summary_metrics():
    assert (SUMMARY.cases, SUMMARY.cases_passed) == (3, 1)
    assert (SUMMARY.turns, SUMMARY.turns_passed) == (4, 2)
    assert (SUMMARY.tool_turns, SUMMARY.tool_turns_passed) == (2, 1)
    assert [(c.category, c.cases, c.passed) for c in SUMMARY.categories] == [
        ("orders", 2, 1),
        ("policy", 1, 0),
    ]
    assert SUMMARY.models == (PRIMARY, FALLBACK)
    assert (SUMMARY.prompt_tokens, SUMMARY.completion_tokens) == (4000, 200)
    assert SUMMARY.total_tokens == 4200
    assert SUMMARY.mean_tokens_per_turn == 1050
    assert (SUMMARY.p50_ms, SUMMARY.p95_ms) == (800, 3000)
    assert SUMMARY.retries == 1
    assert SUMMARY.fallback_turns == 1
    assert SUMMARY.model_error_turns == 1


def test_markdown_has_headline_metrics_table_and_transcripts():
    markdown = render_markdown(CASES, SUMMARY)

    assert "- Date: 2026-11-03 14:05 (store time)" in markdown
    assert f"- Models used: {PRIMARY}, {FALLBACK} (primary {PRIMARY})" in markdown
    assert "- Cases: 3 · Turns: 4" in markdown
    assert "- Case pass rate: 33.3% (1/3)" in markdown
    assert "  - orders: 50.0% (1/2)" in markdown
    assert "  - policy: 0.0% (0/1)" in markdown
    assert "- Tool-selection accuracy: 50.0% (1/2)" in markdown
    assert "- Tokens: 4200 total (4000 prompt + 200 completion), 1050 mean per turn" in markdown
    assert "- Turn latency: p50 800 ms · p95 3000 ms" in markdown
    assert "- Retries: 1" in markdown
    assert "- Fallback-model turns: 1" in markdown
    assert "| orders_ok | orders | PASS |  |" in markdown
    assert (
        "| orders_bad | orders | FAIL | turn 1: missing tools ['get_order_status']; "
        "turn 1: missing text 'a\\|b' |"
    ) in markdown
    assert "### policy_flaky — FAIL" in markdown
    assert "**Cliente:** pedido 1, tel {phone:order_1}" in markdown
    assert "**Lia:** Pedido entregue! Equipe: (67) 3341-4444." in markdown
    assert '`get_order_status` `{"order_id": 1, "phone": "[redacted]"}` (ok)' in markdown


def test_json_report_mirrors_summary_and_cases():
    payload = json.loads(render_json(CASES, SUMMARY))

    assert payload["summary"]["cases_passed"] == 1
    assert payload["summary"]["generated_at"] == GENERATED_AT.isoformat()
    assert payload["summary"]["categories"][0] == {"category": "orders", "cases": 2, "passed": 1}
    assert payload["cases"][0]["turns"][0]["tools"] == [
        {
            "name": "get_order_status",
            "arguments": {"order_id": 1, "phone": REDACTED},
            "outcome": "ok",
        }
    ]
    assert payload["cases"][2]["turns"][0]["model_error"] is True
    assert [case["passed"] for case in payload["cases"]] == [True, False, False]


def test_reports_never_contain_customer_phone_digits():
    leaky = (
        CaseRecord(
            "leak",
            "safety",
            f"descrição {CUSTOMER_PHONE}",
            (turn(reasons=[f"forbidden text '{CUSTOMER_PHONE}'"], reply=f"tel {REDACTED}"),),
        ),
    )
    summary = summarize(leaky, PRIMARY, GENERATED_AT)

    for rendered in (render_markdown(leaky, summary), render_json(leaky, summary)):
        assert not any(digits in rendered for digits in CUSTOMER_DIGITS)


def test_empty_tool_expectations_render_as_not_available():
    cases = (CaseRecord("x", "policy", "d", (turn(),)),)
    markdown = render_markdown(cases, summarize(cases, PRIMARY, GENERATED_AT))

    assert "- Tool-selection accuracy: n/a" in markdown


def test_summary_line_is_a_single_line():
    line = summary_line(SUMMARY)

    assert "\n" not in line
    assert line.startswith("eval: cases 33.3% (1/3), turns 50.0% (2/4)")
    assert "tool selection 50.0% (1/2)" in line
