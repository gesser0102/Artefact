import re

REDACTED = "[redacted]"
SENSITIVE_KEY_PARTS = (
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


def redact_text(text: str) -> str:
    for pattern in SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def is_sensitive_key(key: str) -> bool:
    return any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
