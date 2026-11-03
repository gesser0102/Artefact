import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from emporio_agent.agent.conversation import TurnResult
from emporio_agent.domain.exceptions import ChatModelFailure
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
MAX_CONSECUTIVE_MODEL_ERRORS = 3
AUTHENTICATION_ABORT_REASON = "authentication failed"
CONSECUTIVE_ERRORS_ABORT_REASON = f"{MAX_CONSECUTIVE_MODEL_ERRORS} consecutive model errors"


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
    failure: ChatModelFailure | None

    @property
    def passed(self) -> bool:
        return not self.reasons

    @property
    def model_error(self) -> bool:
        return self.failure is not None

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
        failure=result.failure,
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
        self._records: list[CaseRecord] = []
        self._consecutive_model_errors = 0
        self._aborted_reason: str | None = None

    @property
    def records(self) -> tuple[CaseRecord, ...]:
        return tuple(self._records)

    @property
    def aborted_reason(self) -> str | None:
        return self._aborted_reason

    def run(self, cases: Sequence[EvalCase]) -> tuple[CaseRecord, ...]:
        self._turns_started = 0
        self._records = []
        self._consecutive_model_errors = 0
        self._aborted_reason = None
        for case in cases:
            self._run_case(case)
            if self._aborted_reason is not None:
                break
        return self.records

    def _run_case(self, case: EvalCase) -> None:
        session = self._agent.start_session()
        turns: list[TurnRecord] = []
        try:
            for turn in case.turns:
                turns.append(self._run_turn(session, turn))
                if self._stops_after(turns[-1]):
                    break
        finally:
            if turns:
                self._record(case, turns)

    def _record(self, case: EvalCase, turns: Sequence[TurnRecord]) -> None:
        record = CaseRecord(
            case_id=case.case_id,
            category=case.category,
            description=case.description,
            turns=tuple(turns),
        )
        self._records.append(record)
        if self._on_case is not None:
            self._on_case(record)

    def _stops_after(self, turn: TurnRecord) -> bool:
        if turn.failure is ChatModelFailure.AUTHENTICATION:
            self._aborted_reason = AUTHENTICATION_ABORT_REASON
        elif turn.model_error:
            self._consecutive_model_errors += 1
            if self._consecutive_model_errors >= MAX_CONSECUTIVE_MODEL_ERRORS:
                self._aborted_reason = CONSECUTIVE_ERRORS_ABORT_REASON
        else:
            self._consecutive_model_errors = 0
        return self._aborted_reason is not None

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
