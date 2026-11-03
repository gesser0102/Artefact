from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from emporio_agent.domain.redaction import REDACTED, is_sensitive_key, redact_text

MODEL_STEP_KIND = "model"
TOOL_STEP_KIND = "tool"


class ToolOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    REJECTED = "rejected"
    LOCKED = "locked"


@dataclass(frozen=True)
class ToolTrace:
    name: str
    arguments: Mapping[str, Any]
    duration_ms: int
    outcome: ToolOutcome
    output_chars: int


@dataclass(frozen=True)
class ModelTrace:
    model: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    retries: int


type TraceStep = ToolTrace | ModelTrace


@dataclass(frozen=True)
class TurnTrace:
    steps: tuple[TraceStep, ...] = ()

    @property
    def tool_steps(self) -> tuple[ToolTrace, ...]:
        return tuple(step for step in self.steps if isinstance(step, ToolTrace))

    @property
    def model_steps(self) -> tuple[ModelTrace, ...]:
        return tuple(step for step in self.steps if isinstance(step, ModelTrace))

    @property
    def prompt_tokens(self) -> int:
        return sum(step.prompt_tokens for step in self.model_steps)

    @property
    def completion_tokens(self) -> int:
        return sum(step.completion_tokens for step in self.model_steps)

    @property
    def retries(self) -> int:
        return sum(step.retries for step in self.model_steps)

    @property
    def duration_ms(self) -> int:
        return sum(step.duration_ms for step in self.steps)


def redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return redact_arguments(value)
    if isinstance(value, list | tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, bool):
        return value
    text = str(value)
    return value if redact_text(text) == text else REDACTED


def redact_arguments(arguments: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        redact_text(str(key)): REDACTED if is_sensitive_key(str(key)) else redact_value(value)
        for key, value in arguments.items()
    }


def step_record(step: TraceStep) -> dict[str, Any]:
    kind = TOOL_STEP_KIND if isinstance(step, ToolTrace) else MODEL_STEP_KIND
    return {"kind": kind, **asdict(step)}


def turn_record(session_id: str, turn_number: int, trace: TurnTrace) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "turn": turn_number,
        "steps": [step_record(step) for step in trace.steps],
        "prompt_tokens": trace.prompt_tokens,
        "completion_tokens": trace.completion_tokens,
        "retries": trace.retries,
        "duration_ms": trace.duration_ms,
    }
