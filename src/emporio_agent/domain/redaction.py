import re

from emporio_agent.domain.identity import (
    COUNTRY_CODE,
    INTERNATIONAL_PREFIX,
    MAX_NATIONAL_DIGITS,
    MIN_NATIONAL_DIGITS,
    NON_DIGIT_PATTERN,
    national_number,
)

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
    re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"\bgsk_\w+"),
)
PHONE_RUN_PATTERN = re.compile(r"\+?\(?[0-9][0-9\s().-]*[0-9]")
DIGIT_PATTERN = re.compile(r"[0-9]")
PHONE_OPENERS = (INTERNATIONAL_PREFIX, "(")
MIN_PHONE_DIGITS = MIN_NATIONAL_DIGITS
MAX_PHONE_DIGITS = len(COUNTRY_CODE) + MAX_NATIONAL_DIGITS


def is_phone(text: str) -> bool:
    digits = NON_DIGIT_PATTERN.sub("", text)
    return national_number(digits, text.startswith(INTERNATIONAL_PREFIX)) is not None


def window_begin(run: str, start: int) -> int:
    return start - 1 if start and run[start - 1] in PHONE_OPENERS else start


def phone_window_last(run: str, starts: list[int], first: int) -> int | None:
    begin = window_begin(run, starts[first])
    longest = min(first + MAX_PHONE_DIGITS, len(starts))
    for last in range(longest - 1, first + MIN_PHONE_DIGITS - 2, -1):
        if is_phone(run[begin : starts[last] + 1]):
            return last
    return None


def redact_phone_run(run: str) -> str:
    starts = [match.start() for match in DIGIT_PATTERN.finditer(run)]
    pieces: list[str] = []
    cursor = 0
    first = 0
    while first < len(starts):
        last = phone_window_last(run, starts, first)
        if last is None:
            first += 1
            continue
        pieces.append(f"{run[cursor : window_begin(run, starts[first])]}{REDACTED}")
        cursor = starts[last] + 1
        first = last + 1
    pieces.append(run[cursor:])
    return "".join(pieces)


def redact_text(text: str) -> str:
    for pattern in SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return PHONE_RUN_PATTERN.sub(lambda match: redact_phone_run(match.group()), text)


def is_sensitive_key(key: str) -> bool:
    return any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
