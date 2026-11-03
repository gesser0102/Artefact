import logging
import traceback
from typing import Any

from emporio_agent.domain.redaction import REDACTED, is_sensitive_key, redact_text

LOGGER_NAME = "emporio_agent"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logger = logging.getLogger(LOGGER_NAME)


def configure_logging(debug: bool) -> None:
    logging.basicConfig(format=LOG_FORMAT)
    logger.setLevel(logging.DEBUG if debug else logging.ERROR)


def redact_context(context: dict[str, Any]) -> dict[str, str]:
    return {
        key: REDACTED if is_sensitive_key(key) else redact_text(str(value))
        for key, value in context.items()
    }


def log_failure(level: int, scope: str, error: Exception, context: dict[str, Any]) -> None:
    logger.log(
        level,
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


def log_error(scope: str, error: Exception, **context: Any) -> None:
    log_failure(logging.ERROR, scope, error, context)


def log_warning(scope: str, error: Exception, **context: Any) -> None:
    log_failure(logging.WARNING, scope, error, context)
