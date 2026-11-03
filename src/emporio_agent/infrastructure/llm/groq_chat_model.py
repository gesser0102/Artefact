import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx

from emporio_agent.application.conversation.messages import (
    ChatCompletion,
    ChatMessage,
    Role,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from emporio_agent.domain.exceptions import ChatModelError, ChatModelFailure
from emporio_agent.infrastructure.observability.logging import log_error, log_warning

CHAT_COMPLETIONS_PATH = "/chat/completions"
USER_AGENT = "emporio-agent/0.1 (+httpx)"
MAX_ATTEMPTS_PER_MODEL = 3
BACKOFF_BASE_SECONDS = 1.0
MAX_RETRY_WAIT_SECONDS = 30.0
MAX_TOOL_USE_FAILED_RETRIES = 1
TOOL_USE_FAILED_CODE = "tool_use_failed"
RETRY_AFTER_HEADER = "retry-after"
COMPLETE_SCOPE = "groq_chat_model.complete"
TOOL_CHOICE_AUTO = "auto"
TOOL_CHOICE_NONE = "none"
FUNCTION_TYPE = "function"
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
PARSING_ERRORS = (KeyError, IndexError, TypeError, ValueError, AttributeError)
FALLBACK_FAILURES = frozenset(
    {ChatModelFailure.RATE_LIMITED, ChatModelFailure.UNAVAILABLE, ChatModelFailure.TIMEOUT}
)


@dataclass(frozen=True)
class AttemptFailure:
    reason: ChatModelFailure
    status_code: int | None
    retry_wait: float | None
    switch_model: bool = False
    tool_use_failed: bool = False


@dataclass(frozen=True)
class AttemptSuccess:
    body: Any


def tool_call_payload(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.call_id,
        "type": FUNCTION_TYPE,
        "function": {"name": call.name, "arguments": call.arguments_json},
    }


def message_payload(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [tool_call_payload(call) for call in message.tool_calls]
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def tool_payload(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": FUNCTION_TYPE,
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": dict(spec.parameters),
        },
    }


def backoff_seconds(attempt: int) -> float:
    return BACKOFF_BASE_SECONDS * float(2 ** (attempt - 1))


def retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get(RETRY_AFTER_HEADER)
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return max(seconds, 0.0)


def error_code_of(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error")
    except PARSING_ERRORS:
        return None
    code = error.get("code") if isinstance(error, Mapping) else None
    return code if isinstance(code, str) else None


def rate_limit_failure(response: httpx.Response, attempt: int) -> AttemptFailure:
    wait = retry_after_seconds(response)
    if wait is None:
        wait = backoff_seconds(attempt)
    return AttemptFailure(
        ChatModelFailure.RATE_LIMITED,
        response.status_code,
        retry_wait=wait,
        switch_model=wait > MAX_RETRY_WAIT_SECONDS,
    )


def failure_of(response: httpx.Response, attempt: int) -> AttemptFailure:
    status = response.status_code
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return AttemptFailure(ChatModelFailure.AUTHENTICATION, status, retry_wait=None)
    if status == HTTP_TOO_MANY_REQUESTS:
        return rate_limit_failure(response, attempt)
    if status >= HTTP_SERVER_ERROR:
        return AttemptFailure(ChatModelFailure.UNAVAILABLE, status, backoff_seconds(attempt))
    if status == HTTP_BAD_REQUEST and error_code_of(response) == TOOL_USE_FAILED_CODE:
        return AttemptFailure(
            ChatModelFailure.INVALID_RESPONSE, status, retry_wait=None, tool_use_failed=True
        )
    return AttemptFailure(ChatModelFailure.INVALID_RESPONSE, status, retry_wait=None)


def can_fall_back(failure: AttemptFailure) -> bool:
    return failure.tool_use_failed or failure.reason in FALLBACK_FAILURES


def can_retry_same_model(failure: AttemptFailure, attempt: int, tool_use_retries: int) -> bool:
    if failure.tool_use_failed:
        return tool_use_retries < MAX_TOOL_USE_FAILED_RETRIES
    return (
        failure.retry_wait is not None
        and not failure.switch_model
        and attempt < MAX_ATTEMPTS_PER_MODEL
    )


def arguments_text(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False)


def parse_tool_call(raw: Mapping[str, Any]) -> ToolCall:
    function = raw["function"]
    return ToolCall(
        call_id=str(raw["id"]),
        name=str(function["name"]),
        arguments_json=arguments_text(function.get("arguments")),
    )


def parse_message(raw: Mapping[str, Any]) -> ChatMessage:
    content = raw.get("content")
    if content is not None and not isinstance(content, str):
        raise TypeError("message content must be text")
    tool_calls = tuple(parse_tool_call(call) for call in raw.get("tool_calls") or ())
    return ChatMessage(Role.ASSISTANT, content, tool_calls=tool_calls)


def parse_usage(raw: object) -> TokenUsage:
    usage = raw if isinstance(raw, Mapping) else {}
    return TokenUsage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


def parse_completion(body: Any, model: str, retries: int) -> ChatCompletion:
    return ChatCompletion(
        message=parse_message(body["choices"][0]["message"]),
        model=model,
        usage=parse_usage(body.get("usage")),
        retries=retries,
    )


class GroqChatModel:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        fallback_model: str | None,
        timeout: float,
        max_completion_tokens: int,
        reasoning_effort: str,
        temperature: float,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}{CHAT_COMPLETIONS_PATH}"
        self._api_key = api_key
        self._models = (model,) if fallback_model in (None, model) else (model, fallback_model)
        self._timeout = timeout
        self._max_completion_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort
        self._temperature = temperature
        self._client = http_client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool = True,
    ) -> ChatCompletion:
        attempts = 0
        for index, model in enumerate(self._models):
            payload = self._payload(model, messages, tools, allow_tools)
            result, model_attempts = self._complete_with(model, payload)
            attempts += model_attempts
            if isinstance(result, AttemptSuccess):
                return self._parsed(result.body, model, attempts - 1, model_attempts)
            if not (self._has_model_after(index) and can_fall_back(result)):
                self._fail(result, model, model_attempts)
            self._warn(result, model, model_attempts)
        raise ChatModelError(ChatModelFailure.UNAVAILABLE)

    def _has_model_after(self, index: int) -> bool:
        return index + 1 < len(self._models)

    def _payload(
        self,
        model: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message_payload(message) for message in messages],
            "max_completion_tokens": self._max_completion_tokens,
            "reasoning_effort": self._reasoning_effort,
            "temperature": self._temperature,
        }
        if tools:
            payload["tools"] = [tool_payload(spec) for spec in tools]
            payload["tool_choice"] = TOOL_CHOICE_AUTO if allow_tools else TOOL_CHOICE_NONE
        return payload

    def _complete_with(
        self,
        model: str,
        payload: Mapping[str, Any],
    ) -> tuple[AttemptSuccess | AttemptFailure, int]:
        tool_use_retries = 0
        attempt = 0
        while True:
            attempt += 1
            result = self._attempt(model, payload, attempt)
            if isinstance(result, AttemptSuccess):
                return result, attempt
            if not can_retry_same_model(result, attempt, tool_use_retries):
                return result, attempt
            self._warn(result, model, attempt)
            if result.tool_use_failed:
                tool_use_retries += 1
            elif result.retry_wait is not None:
                self._sleep(result.retry_wait)

    def _attempt(
        self,
        model: str,
        payload: Mapping[str, Any],
        attempt: int,
    ) -> AttemptSuccess | AttemptFailure:
        try:
            response = self._client.post(
                self._url, json=payload, headers=self._headers(), timeout=self._timeout
            )
        except httpx.TimeoutException:
            return AttemptFailure(ChatModelFailure.TIMEOUT, None, backoff_seconds(attempt))
        except httpx.TransportError:
            return AttemptFailure(ChatModelFailure.UNAVAILABLE, None, backoff_seconds(attempt))
        if response.is_success:
            return self._decoded(response)
        return failure_of(response, attempt)

    def _decoded(self, response: httpx.Response) -> AttemptSuccess | AttemptFailure:
        try:
            return AttemptSuccess(response.json())
        except ValueError:
            return AttemptFailure(
                ChatModelFailure.INVALID_RESPONSE, response.status_code, retry_wait=None
            )

    def _parsed(self, body: Any, model: str, retries: int, attempt: int) -> ChatCompletion:
        try:
            return parse_completion(body, model, retries)
        except PARSING_ERRORS as error:
            failure = AttemptFailure(ChatModelFailure.INVALID_RESPONSE, None, retry_wait=None)
            self._fail(failure, model, attempt, cause=error)

    def _warn(self, failure: AttemptFailure, model: str, attempt: int) -> None:
        log_warning(
            COMPLETE_SCOPE,
            ChatModelError(failure.reason),
            status_code=failure.status_code,
            model=model,
            attempt=attempt,
        )

    def _fail(
        self,
        failure: AttemptFailure,
        model: str,
        attempt: int,
        cause: Exception | None = None,
    ) -> NoReturn:
        error = ChatModelError(failure.reason)
        log_error(
            COMPLETE_SCOPE,
            error,
            status_code=failure.status_code,
            model=model,
            attempt=attempt,
        )
        raise error from cause

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "User-Agent": USER_AGENT}
