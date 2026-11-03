import logging
import re
import traceback
from typing import Any

LOGGER_NAME = "emporio_agent"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
REDACTED = "[redacted]"
SENSITIVE_CONTEXT_KEY_PARTS = (
    "phone",
    "telefone",
    "email",
    "secret",
    "token",
    "password",
    "api_key",
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"(?<!\d)(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?\d{4,5}[\s-]?\d{4}(?!\d)"),
    re.compile(r"\bgsk_\w+"),
)

logger = logging.getLogger(LOGGER_NAME)


def configure_logging(debug: bool) -> None:
    logging.basicConfig(format=LOG_FORMAT)
    logger.setLevel(logging.DEBUG if debug else logging.ERROR)


def redact_text(text: str) -> str:
    for pattern in SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_context(context: dict[str, Any]) -> dict[str, str]:
    return {
        key: REDACTED
        if any(part in key.lower() for part in SENSITIVE_CONTEXT_KEY_PARTS)
        else redact_text(str(value))
        for key, value in context.items()
    }


def log_error(scope: str, error: Exception, **context: Any) -> None:
    logger.error(
        "%s %s: %s context=%s",
        scope,
        type(error).__name__,
        redact_text(str(error)),
        redact_context(context),
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "%s traceback:\n%s",
            scope,
            redact_text("".join(traceback.format_exception(error))),
        )
