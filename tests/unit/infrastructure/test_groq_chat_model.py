import json
import logging
from collections.abc import Callable

import httpx
import pytest

from emporio_agent.application.conversation.messages import (
    ChatMessage,
    Role,
    ToolCall,
    ToolSpec,
)
from emporio_agent.domain.exceptions import ChatModelError, ChatModelFailure
from emporio_agent.infrastructure.llm.groq_chat_model import (
    BACKOFF_BASE_SECONDS,
    MAX_ATTEMPTS_PER_MODEL,
    MAX_RETRY_WAIT_SECONDS,
    USER_AGENT,
    GroqChatModel,
)
from emporio_agent.infrastructure.observability.logging import LOGGER_NAME

BASE_URL = "https://groq.test/openai/v1"
API_KEY = "gsk_test_key_that_must_never_leak_123"
PRIMARY = "primary-model"
FALLBACK = "fallback-model"
CUSTOMER_PHONE = "(67) 99812-3456"
SPEC = ToolSpec(
    name="search_products",
    description="Search the catalog.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
)
CONVERSATION = (
    ChatMessage(Role.SYSTEM, "Você é a Lia."),
    ChatMessage(Role.USER, f"meu telefone é {CUSTOMER_PHONE}"),
    ChatMessage(
        Role.ASSISTANT,
        None,
        tool_calls=(ToolCall("call_1", "search_products", '{"query":"violão"}'),),
    ),
    ChatMessage(Role.TOOL, '{"total_matches":0}', tool_call_id="call_1"),
)

type Handler = Callable[[httpx.Request], httpx.Response]


def ok_body(
    content: str | None = "Olá!",
    tool_calls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "role": "assistant",
        "content": content,
        "reasoning": "pensamento interno",
    }
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "model": "whatever",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 12, "total_tokens": 333},
    }


def ok(content: str | None = "Olá!") -> httpx.Response:
    return httpx.Response(200, json=ok_body(content))


def status(status_code: int, headers: dict[str, str] | None = None, **error: str) -> httpx.Response:
    return httpx.Response(status_code, headers=headers, json={"error": {"message": "x", **error}})


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def payload(self, index: int = 0) -> dict[str, object]:
        return json.loads(self.requests[index].content)

    def models(self) -> list[str]:
        return [json.loads(request.content)["model"] for request in self.requests]


def chat_model(recorder: Recorder, fallback: str | None = FALLBACK) -> GroqChatModel:
    return GroqChatModel(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=PRIMARY,
        fallback_model=fallback,
        timeout=5.0,
        max_completion_tokens=256,
        reasoning_effort="low",
        temperature=0.3,
        http_client=httpx.Client(transport=httpx.MockTransport(recorder.handler)),
        sleep=recorder.sleeps.append,
    )


def failure_of(recorder: Recorder, fallback: str | None = FALLBACK) -> ChatModelFailure:
    with pytest.raises(ChatModelError) as raised:
        chat_model(recorder, fallback).complete(CONVERSATION, [SPEC])
    return raised.value.reason


def test_request_shape_follows_the_openai_contract():
    recorder = Recorder(ok())

    chat_model(recorder).complete(CONVERSATION, [SPEC])

    request = recorder.requests[0]
    payload = recorder.payload()
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["user-agent"] == USER_AGENT
    assert payload["model"] == PRIMARY
    assert payload["tool_choice"] == "auto"
    assert payload["max_completion_tokens"] == 256
    assert payload["reasoning_effort"] == "low"
    assert payload["temperature"] == 0.3
    assert "parallel_tool_calls" not in payload
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_products",
                "description": "Search the catalog.",
                "parameters": SPEC.parameters,
            },
        }
    ]
    assert payload["messages"] == [
        {"role": "system", "content": "Você é a Lia."},
        {"role": "user", "content": f"meu telefone é {CUSTOMER_PHONE}"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search_products", "arguments": '{"query":"violão"}'},
                }
            ],
        },
        {"role": "tool", "content": '{"total_matches":0}', "tool_call_id": "call_1"},
    ]


def test_disallowing_tools_sends_tool_choice_none():
    recorder = Recorder(ok())

    chat_model(recorder).complete(CONVERSATION, [SPEC], allow_tools=False)

    assert recorder.payload()["tool_choice"] == "none"


def test_tools_and_tool_choice_are_omitted_without_tools():
    recorder = Recorder(ok())

    chat_model(recorder).complete(CONVERSATION, [])

    assert "tools" not in recorder.payload()
    assert "tool_choice" not in recorder.payload()


def test_plain_answer_is_parsed_without_reasoning():
    recorder = Recorder(ok("Oi, tudo bem?"))

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert result.message == ChatMessage(Role.ASSISTANT, "Oi, tudo bem?")
    assert result.model == PRIMARY
    assert result.usage.prompt_tokens == 321
    assert result.usage.completion_tokens == 12
    assert result.retries == 0


def test_tool_calls_are_parsed_in_order():
    calls = [
        {
            "id": "fc_1",
            "type": "function",
            "function": {"name": "search_products", "arguments": '{"query":"yamaha"}'},
        },
        {"id": "fc_2", "type": "function", "function": {"name": "list_categories"}},
        {"id": "fc_3", "type": "function", "function": {"name": "get_product", "arguments": {}}},
    ]
    recorder = Recorder(httpx.Response(200, json=ok_body(None, calls)))

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert result.message.content is None
    assert result.message.tool_calls == (
        ToolCall("fc_1", "search_products", '{"query":"yamaha"}'),
        ToolCall("fc_2", "list_categories", ""),
        ToolCall("fc_3", "get_product", "{}"),
    )


def test_rate_limit_with_short_retry_after_waits_and_retries():
    recorder = Recorder(status(429, {"retry-after": "3"}), ok())

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert recorder.sleeps == [3.0]
    assert recorder.models() == [PRIMARY, PRIMARY]
    assert result.retries == 1
    assert result.model == PRIMARY


def test_rate_limit_with_long_retry_after_switches_to_the_fallback():
    long_wait = str(int(MAX_RETRY_WAIT_SECONDS) + 1)
    recorder = Recorder(status(429, {"retry-after": long_wait}), ok())

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert recorder.sleeps == []
    assert recorder.models() == [PRIMARY, FALLBACK]
    assert result.model == FALLBACK
    assert result.retries == 1


def test_long_rate_limit_without_fallback_raises_rate_limited():
    recorder = Recorder(status(429, {"retry-after": "120"}))

    assert failure_of(recorder, fallback=None) is ChatModelFailure.RATE_LIMITED
    assert len(recorder.requests) == 1


def test_rate_limit_on_both_models_raises_rate_limited():
    recorder = Recorder(status(429, {"retry-after": "999"}), status(429, {"retry-after": "999"}))

    assert failure_of(recorder) is ChatModelFailure.RATE_LIMITED
    assert recorder.models() == [PRIMARY, FALLBACK]


def test_server_errors_back_off_exponentially_then_use_the_fallback():
    recorder = Recorder(status(500), status(502), status(503), ok())

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert recorder.sleeps == [BACKOFF_BASE_SECONDS, BACKOFF_BASE_SECONDS * 2]
    assert recorder.models() == [PRIMARY] * MAX_ATTEMPTS_PER_MODEL + [FALLBACK]
    assert result.model == FALLBACK
    assert result.retries == MAX_ATTEMPTS_PER_MODEL


def test_server_errors_on_both_models_raise_unavailable():
    recorder = Recorder(*[status(503) for _ in range(2 * MAX_ATTEMPTS_PER_MODEL)])

    assert failure_of(recorder) is ChatModelFailure.UNAVAILABLE
    assert len(recorder.requests) == 2 * MAX_ATTEMPTS_PER_MODEL
    assert recorder.sleeps == [1.0, 2.0, 1.0, 2.0]


def test_timeouts_are_retried_and_reported_as_timeout():
    recorder = Recorder(*[httpx.ReadTimeout("timed out") for _ in range(MAX_ATTEMPTS_PER_MODEL)])

    assert failure_of(recorder, fallback=None) is ChatModelFailure.TIMEOUT
    assert len(recorder.requests) == MAX_ATTEMPTS_PER_MODEL


def test_timeout_then_success_counts_the_retry():
    recorder = Recorder(httpx.ConnectTimeout("timed out"), ok())

    assert chat_model(recorder).complete(CONVERSATION, [SPEC]).retries == 1
    assert recorder.sleeps == [BACKOFF_BASE_SECONDS]


def test_connection_errors_are_reported_as_unavailable():
    recorder = Recorder(*[httpx.ConnectError("refused") for _ in range(MAX_ATTEMPTS_PER_MODEL)])

    assert failure_of(recorder, fallback=None) is ChatModelFailure.UNAVAILABLE


@pytest.mark.parametrize("code", [401, 403])
def test_authentication_errors_are_not_retried(code):
    recorder = Recorder(status(code))

    assert failure_of(recorder) is ChatModelFailure.AUTHENTICATION
    assert len(recorder.requests) == 1
    assert recorder.sleeps == []


def test_tool_use_failed_is_retried_once():
    recorder = Recorder(status(400, code="tool_use_failed"), ok("Pronto"))

    result = chat_model(recorder).complete(CONVERSATION, [SPEC])

    assert result.message.content == "Pronto"
    assert result.retries == 1
    assert recorder.models() == [PRIMARY, PRIMARY]


def test_repeated_tool_use_failed_raises_invalid_response():
    recorder = Recorder(status(400, code="tool_use_failed"), status(400, code="tool_use_failed"))

    assert failure_of(recorder) is ChatModelFailure.INVALID_RESPONSE
    assert len(recorder.requests) == 2


@pytest.mark.parametrize("response", [status(400), status(404), status(422)])
def test_other_client_errors_raise_invalid_response_without_retry(response):
    recorder = Recorder(response)

    assert failure_of(recorder) is ChatModelFailure.INVALID_RESPONSE
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={"choices": [{"message": {"content": 7}}]}),
        httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{"id": "x"}]}}]}),
    ],
)
def test_malformed_success_bodies_raise_invalid_response(response):
    recorder = Recorder(response)

    assert failure_of(recorder) is ChatModelFailure.INVALID_RESPONSE
    assert len(recorder.requests) == 1


def test_secrets_and_message_contents_never_reach_logs_or_errors(caplog):
    logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG)
    responses: list[httpx.Response | Exception] = [
        status(429, {"retry-after": "1"}),
        status(500),
        httpx.ReadTimeout(f"timed out {API_KEY}"),
        status(429, {"retry-after": "999"}),
    ]
    recorder = Recorder(*responses)

    with pytest.raises(ChatModelError) as raised:
        chat_model(recorder).complete(CONVERSATION, [SPEC])

    digits = "".join(char for char in CUSTOMER_PHONE if char.isdigit())
    exposed = f"{caplog.text}\n{raised.value}\n{raised.value!r}"
    assert "groq_chat_model.complete" in caplog.text
    assert PRIMARY in caplog.text
    assert "500" in caplog.text
    for secret in (API_KEY, CUSTOMER_PHONE, digits, "Você é a Lia", "violão"):
        assert secret not in exposed


def test_client_repr_does_not_expose_the_key():
    assert API_KEY not in repr(chat_model(Recorder()))
