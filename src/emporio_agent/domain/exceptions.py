from enum import StrEnum


class DataLoadError(Exception):
    pass


class InvalidReceivedOnError(Exception):
    pass


class TraceWriteError(Exception):
    pass


class EvalCaseError(Exception):
    pass


class ChatModelFailure(StrEnum):
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    AUTHENTICATION = "authentication"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"


class ChatModelError(Exception):
    def __init__(self, reason: ChatModelFailure) -> None:
        super().__init__(f"chat model request failed: {reason.value}")
        self.reason = reason
