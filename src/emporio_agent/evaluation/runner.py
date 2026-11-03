import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from emporio_agent.agent.conversation import TurnResult
from emporio_agent.evaluation.cases import EvalCase, EvalTurn
from emporio_agent.evaluation.checks import (
    CustomerContacts,
    check_no_customer_pii,
    check_text,
    check_tools,
    mask_personal_data,
)

MODEL_ERROR_REASON = "model_error"
MILLISECONDS_PER_SECOND = 1000


class ChatSession(Protocol):
    def reply(self, user_text: str) -> TurnResult: ...


class ChatAgent(Protocol):
    def start_session(self) -> ChatSession: ...


class PlaceholderResolver(Protocol):
    @property
    def contacts(self) -> CustomerContacts: ...

    def resolve(self, text: str) -> str: ...


type Sleeper = Callable[[float], None]
type Timer = Callable[[], float]


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: Mapping[str, Any]
    outcome: str


@dataclass(frozen=True)
class TurnRecord:
    user: str
    reply: str
    tools: tuple[ToolCallRecord, ...]
    prompt_tokens: int
    completion_tokens: int
    models: tuple[str, ...]
    retries: int
    duration_ms: int
    reasons: tuple[str, ...]
    has_tool_expectations: bool
    tools_passed: bool
    model_error: bool

    @property
    def passed(self) -> bool:
        return not self.reasons

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    category: str
    description: str
    turns: tuple[TurnRecord, ...]

    @property
    def passed(self) -> bool:
        return all(turn.passed for turn in self.turns)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(
            f"turn {number}: {reason}"
            for number, turn in enumerate(self.turns, start=1)
            for reason in turn.reasons
        )


type CaseObserver = Callable[[CaseRecord], None]


def tool_records(result: TurnResult) -> tuple[ToolCallRecord, ...]:
    return tuple(
        ToolCallRecord(name=step.name, arguments=dict(step.arguments), outcome=step.outcome.value)
        for step in result.trace.tool_steps
    )


def models_of(result: TurnResult) -> tuple[str, ...]:
    return tuple(dict.fromkeys(step.model for step in result.trace.model_steps))


def turn_reasons(
    turn: EvalTurn,
    result: TurnResult,
    contacts: CustomerContacts,
) -> tuple[list[str], list[str]]:
    if result.failure is not None:
        return [MODEL_ERROR_REASON], [MODEL_ERROR_REASON]
    called = [step.name for step in result.trace.tool_steps]
    tool_reasons = check_tools(turn.expect, called)
    reasons = tool_reasons + check_text(turn.expect, result.text)
    if turn.expect.no_customer_pii:
        reasons += check_no_customer_pii(result.text, contacts)
    return reasons, tool_reasons


def evaluate_turn(
    turn: EvalTurn,
    result: TurnResult,
    duration_ms: int,
    contacts: CustomerContacts,
) -> TurnRecord:
    reasons, tool_reasons = turn_reasons(turn, result, contacts)
    return TurnRecord(
        user=mask_personal_data(turn.user),
        reply=mask_personal_data(result.text),
        tools=tool_records(result),
        prompt_tokens=result.trace.prompt_tokens,
        completion_tokens=result.trace.completion_tokens,
        models=models_of(result),
        retries=result.trace.retries,
        duration_ms=duration_ms,
        reasons=tuple(reasons),
        has_tool_expectations=turn.expect.has_tool_expectations,
        tools_passed=not tool_reasons,
        model_error=result.failure is not None,
    )


class EvalRunner:
    def __init__(
        self,
        agent: ChatAgent,
        resolver: PlaceholderResolver,
        pause_seconds: float,
        sleep: Sleeper,
        timer: Timer = time.perf_counter,
        on_case: CaseObserver | None = None,
    ) -> None:
        self._agent = agent
        self._resolver = resolver
        self._pause_seconds = pause_seconds
        self._sleep = sleep
        self._timer = timer
        self._on_case = on_case
        self._turns_started = 0

    def run(self, cases: Sequence[EvalCase]) -> tuple[CaseRecord, ...]:
        self._turns_started = 0
        return tuple(self._run_case(case) for case in cases)

    def _run_case(self, case: EvalCase) -> CaseRecord:
        session = self._agent.start_session()
        record = CaseRecord(
            case_id=case.case_id,
            category=case.category,
            description=case.description,
            turns=tuple(self._run_turn(session, turn) for turn in case.turns),
        )
        if self._on_case is not None:
            self._on_case(record)
        return record

    def _run_turn(self, session: ChatSession, turn: EvalTurn) -> TurnRecord:
        self._pause_between_turns()
        user_text = self._resolver.resolve(turn.user)
        started = self._timer()
        result = session.reply(user_text)
        duration_ms = round((self._timer() - started) * MILLISECONDS_PER_SECOND)
        return evaluate_turn(turn, result, duration_ms, self._resolver.contacts)

    def _pause_between_turns(self) -> None:
        if self._turns_started and self._pause_seconds > 0:
            self._sleep(self._pause_seconds)
        self._turns_started += 1
