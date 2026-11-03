import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from emporio_agent.evaluation.checks import mask_personal_data
from emporio_agent.evaluation.runner import CaseRecord, ToolCallRecord, TurnRecord

REPORT_TITLE = "# Lia evaluation report — Empório da Música"
DATE_FORMAT = "%Y-%m-%d %H:%M"
STORE_TIME_LABEL = "store time"
PASS_LABEL = "PASS"
FAIL_LABEL = "FAIL"
NOT_AVAILABLE = "n/a"
NO_TOOLS_LABEL = "no tools"
REASON_SEPARATOR = "; "
MEDIAN_PERCENTILE = 50
TAIL_PERCENTILE = 95
JSON_INDENT = 2
STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"


@dataclass(frozen=True)
class CategorySummary:
    category: str
    cases: int
    passed: int


@dataclass(frozen=True)
class EvalSummary:
    generated_at: datetime
    primary_model: str
    models: tuple[str, ...]
    cases: int
    cases_passed: int
    turns: int
    turns_passed: int
    categories: tuple[CategorySummary, ...]
    tool_turns: int
    tool_turns_passed: int
    prompt_tokens: int
    completion_tokens: int
    p50_ms: int
    p95_ms: int
    retries: int
    fallback_turns: int
    model_error_turns: int
    aborted_reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.aborted_reason is None

    @property
    def status(self) -> str:
        return STATUS_COMPLETE if self.complete else STATUS_PARTIAL

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def mean_tokens_per_turn(self) -> float:
        return self.total_tokens / self.turns if self.turns else 0.0


def all_turns(cases: Sequence[CaseRecord]) -> list[TurnRecord]:
    return [turn for case in cases for turn in case.turns]


def percentile(values: Sequence[int], rank: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(math.ceil(rank / 100 * len(ordered)) - 1, 0)
    return ordered[index]


def category_summaries(cases: Sequence[CaseRecord]) -> tuple[CategorySummary, ...]:
    categories = dict.fromkeys(case.category for case in cases)
    return tuple(
        CategorySummary(
            category=category,
            cases=sum(1 for case in cases if case.category == category),
            passed=sum(1 for case in cases if case.category == category and case.passed),
        )
        for category in categories
    )


def uses_fallback(turn: TurnRecord, primary_model: str) -> bool:
    return any(model != primary_model for model in turn.models)


def summarize(
    cases: Sequence[CaseRecord],
    primary_model: str,
    generated_at: datetime,
    aborted_reason: str | None = None,
) -> EvalSummary:
    turns = all_turns(cases)
    tool_turns = [turn for turn in turns if turn.has_tool_expectations]
    durations = [turn.duration_ms for turn in turns]
    return EvalSummary(
        generated_at=generated_at,
        primary_model=primary_model,
        models=tuple(sorted({model for turn in turns for model in turn.models})),
        cases=len(cases),
        cases_passed=sum(1 for case in cases if case.passed),
        turns=len(turns),
        turns_passed=sum(1 for turn in turns if turn.passed),
        categories=category_summaries(cases),
        tool_turns=len(tool_turns),
        tool_turns_passed=sum(1 for turn in tool_turns if turn.tools_passed),
        prompt_tokens=sum(turn.prompt_tokens for turn in turns),
        completion_tokens=sum(turn.completion_tokens for turn in turns),
        p50_ms=percentile(durations, MEDIAN_PERCENTILE),
        p95_ms=percentile(durations, TAIL_PERCENTILE),
        retries=sum(turn.retries for turn in turns),
        fallback_turns=sum(1 for turn in turns if uses_fallback(turn, primary_model)),
        model_error_turns=sum(1 for turn in turns if turn.model_error),
        aborted_reason=aborted_reason,
    )


def status_label(summary: EvalSummary) -> str:
    if summary.aborted_reason is None:
        return summary.status
    return f"{summary.status} (aborted: {summary.aborted_reason})"


def format_rate(part: int, whole: int) -> str:
    if not whole:
        return NOT_AVAILABLE
    return f"{part / whole:.1%} ({part}/{whole})"


def result_label(passed: bool) -> str:
    return PASS_LABEL if passed else FAIL_LABEL


def table_cell(text: str) -> str:
    return mask_personal_data(text).replace("|", "\\|").replace("\n", " ")


def summary_line(summary: EvalSummary) -> str:
    return (
        f"eval: cases {format_rate(summary.cases_passed, summary.cases)}, "
        f"turns {format_rate(summary.turns_passed, summary.turns)}, "
        f"tool selection {format_rate(summary.tool_turns_passed, summary.tool_turns)}, "
        f"tokens {summary.total_tokens}, p95 {summary.p95_ms} ms, "
        f"model errors {summary.model_error_turns}, status {status_label(summary)}"
    )


def header_lines(summary: EvalSummary) -> list[str]:
    category_lines = [
        f"  - {category.category}: {format_rate(category.passed, category.cases)}"
        for category in summary.categories
    ]
    return [
        REPORT_TITLE,
        "",
        f"- Date: {summary.generated_at.strftime(DATE_FORMAT)} ({STORE_TIME_LABEL})",
        f"- Status: {status_label(summary)}",
        f"- Models used: {', '.join(summary.models) or NOT_AVAILABLE} "
        f"(primary {summary.primary_model})",
        f"- Cases: {summary.cases} · Turns: {summary.turns}",
        f"- Case pass rate: {format_rate(summary.cases_passed, summary.cases)}",
        f"- Turn pass rate: {format_rate(summary.turns_passed, summary.turns)}",
        "- Pass rate per category:",
        *category_lines,
        f"- Tool-selection accuracy: {format_rate(summary.tool_turns_passed, summary.tool_turns)}",
        f"- Tokens: {summary.total_tokens} total "
        f"({summary.prompt_tokens} prompt + {summary.completion_tokens} completion), "
        f"{summary.mean_tokens_per_turn:.0f} mean per turn",
        f"- Turn latency: p50 {summary.p50_ms} ms · p95 {summary.p95_ms} ms",
        f"- Retries: {summary.retries}",
        f"- Fallback-model turns: {summary.fallback_turns}",
        f"- Model-error turns: {summary.model_error_turns}",
    ]


def case_table_lines(cases: Sequence[CaseRecord]) -> list[str]:
    rows = [
        f"| {table_cell(case.case_id)} | {table_cell(case.category)} | "
        f"{result_label(case.passed)} | {table_cell(REASON_SEPARATOR.join(case.reasons))} |"
        for case in cases
    ]
    return [
        "## Cases",
        "",
        "| Case | Category | Result | Failed reasons |",
        "| --- | --- | --- | --- |",
        *rows,
    ]


def tool_label(tool: ToolCallRecord) -> str:
    arguments = json.dumps(tool.arguments, ensure_ascii=False, sort_keys=True)
    return f"`{tool.name}` `{mask_personal_data(arguments)}` ({tool.outcome})"


def turn_lines(number: int, turn: TurnRecord) -> list[str]:
    tools = ", ".join(tool_label(tool) for tool in turn.tools) or NO_TOOLS_LABEL
    verdict = result_label(turn.passed)
    if turn.reasons:
        verdict = f"{verdict}: {mask_personal_data(REASON_SEPARATOR.join(turn.reasons))}"
    return [
        f"**Cliente:** {mask_personal_data(turn.user)}",
        "",
        f"**Lia:** {mask_personal_data(turn.reply)}",
        "",
        f"> Turn {number} · {verdict} · tools: {tools} · "
        f"tokens {turn.prompt_tokens}+{turn.completion_tokens} · retries {turn.retries} · "
        f"{turn.duration_ms} ms · models {', '.join(turn.models) or NOT_AVAILABLE}",
        "",
    ]


def transcript_lines(case: CaseRecord) -> list[str]:
    lines = [
        f"### {table_cell(case.case_id)} — {result_label(case.passed)}",
        "",
        f"_{table_cell(case.category)} · {table_cell(case.description)}_",
        "",
    ]
    for number, turn in enumerate(case.turns, start=1):
        lines += turn_lines(number, turn)
    return lines


def render_markdown(cases: Sequence[CaseRecord], summary: EvalSummary) -> str:
    lines = [*header_lines(summary), "", *case_table_lines(cases), "", "## Transcripts", ""]
    for case in cases:
        lines += transcript_lines(case)
    return "\n".join(lines).rstrip() + "\n"


def tool_payload(tool: ToolCallRecord) -> dict[str, Any]:
    return {"name": tool.name, "arguments": dict(tool.arguments), "outcome": tool.outcome}


def turn_payload(turn: TurnRecord) -> dict[str, Any]:
    return {
        "user": mask_personal_data(turn.user),
        "reply": mask_personal_data(turn.reply),
        "passed": turn.passed,
        "reasons": [mask_personal_data(reason) for reason in turn.reasons],
        "tools": [tool_payload(tool) for tool in turn.tools],
        "has_tool_expectations": turn.has_tool_expectations,
        "tools_passed": turn.tools_passed,
        "model_error": turn.model_error,
        "failure": None if turn.failure is None else turn.failure.value,
        "prompt_tokens": turn.prompt_tokens,
        "completion_tokens": turn.completion_tokens,
        "models": list(turn.models),
        "retries": turn.retries,
        "duration_ms": turn.duration_ms,
    }


def case_payload(case: CaseRecord) -> dict[str, Any]:
    return {
        "id": case.case_id,
        "category": case.category,
        "description": mask_personal_data(case.description),
        "passed": case.passed,
        "turns": [turn_payload(turn) for turn in case.turns],
    }


def summary_payload(summary: EvalSummary) -> dict[str, Any]:
    return {
        "generated_at": summary.generated_at.isoformat(),
        "status": summary.status,
        "aborted_reason": summary.aborted_reason,
        "primary_model": summary.primary_model,
        "models": list(summary.models),
        "cases": summary.cases,
        "cases_passed": summary.cases_passed,
        "turns": summary.turns,
        "turns_passed": summary.turns_passed,
        "categories": [
            {"category": category.category, "cases": category.cases, "passed": category.passed}
            for category in summary.categories
        ],
        "tool_turns": summary.tool_turns,
        "tool_turns_passed": summary.tool_turns_passed,
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "mean_tokens_per_turn": round(summary.mean_tokens_per_turn, 1),
        "p50_ms": summary.p50_ms,
        "p95_ms": summary.p95_ms,
        "retries": summary.retries,
        "fallback_turns": summary.fallback_turns,
        "model_error_turns": summary.model_error_turns,
    }


def render_json(cases: Sequence[CaseRecord], summary: EvalSummary) -> str:
    document = {
        "summary": summary_payload(summary),
        "cases": [case_payload(case) for case in cases],
    }
    return json.dumps(document, ensure_ascii=False, indent=JSON_INDENT) + "\n"
