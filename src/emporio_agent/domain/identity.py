import re

COUNTRY_CODE = "55"
INTERNATIONAL_PREFIX = "+"
MIN_NATIONAL_DIGITS = 10
MAX_NATIONAL_DIGITS = 11
PHONE_TEXT_PATTERN = re.compile(r"\+?[0-9\s().-]+", re.ASCII)
NON_DIGIT_PATTERN = re.compile(r"[^0-9]")
NATIONAL_NUMBER_PATTERN = re.compile(r"[1-9]{2}(?:9[0-9]{8}|[2-5][0-9]{7})")


def national_number(digits: str, international: bool) -> str | None:
    if international or len(digits) > MAX_NATIONAL_DIGITS:
        if not digits.startswith(COUNTRY_CODE):
            return None
        digits = digits.removeprefix(COUNTRY_CODE)
    return digits if NATIONAL_NUMBER_PATTERN.fullmatch(digits) else None


def normalize_phone(raw: str) -> str | None:
    text = raw.strip()
    if PHONE_TEXT_PATTERN.fullmatch(text) is None:
        return None
    digits = NON_DIGIT_PATTERN.sub("", text)
    return national_number(digits, text.startswith(INTERNATIONAL_PREFIX))
