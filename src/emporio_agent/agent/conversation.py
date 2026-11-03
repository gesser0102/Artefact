import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from emporio_agent.agent.guardrails import (
    EMPTY_ANSWER_REPLY,
    LOCKED_OUTPUT,
    MAX_TOOL_STEPS_PER_TURN,
    MESSAGE_TOO_LONG_REPLY,
    IdentityAttemptGuard,
    is_message_too_long,
    reply_for_failure,
)
from emporio_agent.agent.history import model_input
from emporio_agent.agent.prompts import build_system_prompt
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.agent.tools.registry import TOOL_HANDLERS, TOOL_SPECS
from emporio_agent.agent.tools.serialization import (
    INVALID_ARGUMENTS_ERROR,
    TOOL_FAILED_ERROR,
    UNKNOWN_TOOL_ERROR,
    error_code_of,
    parse_tool_arguments,
    serialize_error,
    to_tool_json,
)
from emporio_agent.agent.tracing import (
    ModelTrace,
    ToolOutcome,
    ToolTrace,
    TraceStep,
    TurnTrace,
    redact_arguments,
    turn_record,
)
from emporio_agent.application.conversation.messages import (
    ChatCompletion,
    ChatMessage,
    Role,
    ToolCall,
)
from emporio_agent.application.policies.dtos import PolicyIndexEntry
from emporio_agent.application.ports import ChatModel, Clock, TraceSink
from emporio_agent.domain.exceptions import ChatModelError, ChatModelFailure, TraceWriteError
from emporio_agent.domain.redaction import redact_text

UNKNOWN_TOOL_OUTPUT = to_tool_json(serialize_error(UNKNOWN_TOOL_ERROR))
INVALID_ARGUMENTS_OUTPUT = to_tool_json(serialize_error(INVALID_ARGUMENTS_ERROR))
TOOL_FAILED_OUTPUT = to_tool_json(serialize_error(TOOL_FAILED_ERROR))
MAX_TRACED_TOOL_NAME_CHARS = 64
MILLISECONDS_PER_SECOND = 1000
TRACE_SCOPE = "agent.trace"
TURN_SCOPE = "agent.turn"

type PolicyIndexProvider = Callable[[], Sequence[PolicyIndexEntry]]
type Timer = Callable[[], float]


@dataclass(frozen=True)
class TurnResult:
    text: str
    trace: TurnTrace
    failure: ChatModelFailure | None = None


@dataclass(frozen=True)
class ToolExecution:
    output: str
    outcome: ToolOutcome
    arguments: dict[str, object]


def elapsed_ms(timer: Timer, started: float) -> int:
    return round((timer() - started) * MILLISECONDS_PER_SECOND)


def final_text_of(message: ChatMessage) -> str:
    text = (message.content or "").strip()
    return text or EMPTY_ANSWER_REPLY


def traced_tool_name(name: str) -> str:
    return redact_text(name)[:MAX_TRACED_TOOL_NAME_CHARS]


class Session:
    def __init__(
        self,
        session_id: str,
        system_prompt: str,
        model: ChatModel,
        tools: ToolContext,
        trace_sink: TraceSink | None,
        timer: Timer,
    ) -> None:
        self.session_id = session_id
        self._system_message = ChatMessage(Role.SYSTEM, system_prompt)
        self._model = model
        self._tools = tools
        self._trace_sink = trace_sink
        self._timer = timer
        self._history: list[ChatMessage] = []
        self._guard = IdentityAttemptGuard()
        self._turns = 0

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    def reply(self, user_text: str) -> TurnResult:
        self._turns += 1
        if is_message_too_long(user_text):
            return self._finish(MESSAGE_TOO_LONG_REPLY, [])
        user_message = ChatMessage(Role.USER, user_text)
        turn_messages: list[ChatMessage] = [user_message]
        steps: list[TraceStep] = []
        try:
            text = self._run_turn(turn_messages, steps)
        except ChatModelError as error:
            self._history.append(user_message)
            return self._finish(reply_for_failure(error.reason), steps, error.reason)
        except Exception as error:
            self._tools.report_error(TURN_SCOPE, error)
            self._history.append(user_message)
            return self._finish(
                reply_for_failure(ChatModelFailure.UNAVAILABLE), steps, ChatModelFailure.UNAVAILABLE
            )
        self._history.extend(turn_messages)
        return self._finish(text, steps)

    def _run_turn(self, turn_messages: list[ChatMessage], steps: list[TraceStep]) -> str:
        message = self._complete(turn_messages, steps, allow_tools=True)
        tool_rounds = 0
        while message.tool_calls and tool_rounds < MAX_TOOL_STEPS_PER_TURN:
            turn_messages.append(
                ChatMessage(Role.ASSISTANT, message.content, tool_calls=message.tool_calls)
            )
            for call in message.tool_calls:
                turn_messages.append(self._execute_tool_call(call, steps))
            tool_rounds += 1
            message = self._complete(
                turn_messages, steps, allow_tools=tool_rounds < MAX_TOOL_STEPS_PER_TURN
            )
        text = final_text_of(message)
        turn_messages.append(ChatMessage(Role.ASSISTANT, text))
        return text

    def _complete(
        self,
        turn_messages: Sequence[ChatMessage],
        steps: list[TraceStep],
        allow_tools: bool,
    ) -> ChatMessage:
        started = self._timer()
        completion = self._model.complete(
            model_input(self._system_message, [*self._history, *turn_messages]),
            TOOL_SPECS,
            allow_tools=allow_tools,
        )
        steps.append(self._model_trace(completion, elapsed_ms(self._timer, started)))
        return completion.message

    def _model_trace(self, completion: ChatCompletion, duration_ms: int) -> ModelTrace:
        return ModelTrace(
            model=completion.model,
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
            duration_ms=duration_ms,
            retries=completion.retries,
        )

    def _execute_tool_call(self, call: ToolCall, steps: list[TraceStep]) -> ChatMessage:
        started = self._timer()
        execution = self._run_tool(call)
        steps.append(
            ToolTrace(
                name=traced_tool_name(call.name),
                arguments=redact_arguments(execution.arguments),
                duration_ms=elapsed_ms(self._timer, started),
                outcome=execution.outcome,
                output_chars=len(execution.output),
            )
        )
        return ChatMessage(Role.TOOL, execution.output, tool_call_id=call.call_id)

    def _run_tool(self, call: ToolCall) -> ToolExecution:
        handler = TOOL_HANDLERS.get(call.name)
        if handler is None:
            return ToolExecution(UNKNOWN_TOOL_OUTPUT, ToolOutcome.REJECTED, {})
        scope = f"agent.tools.{call.name}"
        try:
            arguments = parse_tool_arguments(call.arguments_json)
        except ValueError as error:
            self._tools.report_rejected_input(scope, error)
            return ToolExecution(INVALID_ARGUMENTS_OUTPUT, ToolOutcome.REJECTED, {})
        if self._guard.blocks(call.name):
            return ToolExecution(LOCKED_OUTPUT, ToolOutcome.LOCKED, arguments)
        try:
            output = handler(self._tools, arguments)
        except Exception as error:
            self._tools.report_error(scope, error)
            return ToolExecution(TOOL_FAILED_OUTPUT, ToolOutcome.ERROR, arguments)
        self._guard.observe(call.name, output)
        rejected = error_code_of(output) == INVALID_ARGUMENTS_ERROR
        return ToolExecution(
            output, ToolOutcome.REJECTED if rejected else ToolOutcome.OK, arguments
        )

    def _finish(
        self,
        text: str,
        steps: Sequence[TraceStep],
        failure: ChatModelFailure | None = None,
    ) -> TurnResult:
        trace = TurnTrace(tuple(steps))
        self._write_trace(trace)
        return TurnResult(text=text, trace=trace, failure=failure)

    def _write_trace(self, trace: TurnTrace) -> None:
        if self._trace_sink is None:
            return
        try:
            self._trace_sink.write(turn_record(self.session_id, self._turns, trace))
        except TraceWriteError as error:
            self._tools.report_error(TRACE_SCOPE, error)


def new_session_id() -> str:
    return uuid.uuid4().hex


class ConversationAgent:
    def __init__(
        self,
        model: ChatModel,
        tools: ToolContext,
        clock: Clock,
        policy_index: PolicyIndexProvider,
        trace_sink: TraceSink | None = None,
        timer: Timer = time.perf_counter,
    ) -> None:
        self._model = model
        self._tools = tools
        self._clock = clock
        self._policy_index = policy_index
        self._trace_sink = trace_sink
        self._timer = timer

    def start_session(self) -> Session:
        return Session(
            session_id=new_session_id(),
            system_prompt=build_system_prompt(self._clock.now(), self._policy_index()),
            model=self._model,
            tools=self._tools,
            trace_sink=self._trace_sink,
            timer=self._timer,
        )
