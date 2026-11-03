import pytest

from emporio_agent.domain.identity import normalize_phone

NATIONAL_MOBILE = "11912345678"
FULLWIDTH_DIGITS = "".join(chr(ord(digit) + 0xFEE0) for digit in NATIONAL_MOBILE)


@pytest.mark.parametrize(
    "raw",
    [
        "(11) 91234-5678",
        "11912345678",
        "+55 11 91234-5678",
        "55 11 91234-5678",
        "+5511912345678",
        "5511912345678",
        "11 91234 5678",
        "11.91234.5678",
        "  (11) 91234-5678  ",
        "+55 (11) 91234-5678",
    ],
)
def test_accepted_formats_become_ddd_plus_number(raw):
    assert normalize_phone(raw) == NATIONAL_MOBILE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(55) 99123-4567", "55991234567"),
        ("55991234567", "55991234567"),
        ("+55 55 99123-4567", "55991234567"),
        ("55 55 99123-4567", "55991234567"),
        ("555599123456", None),
        ("(55) 3321-4500", "5533214500"),
        ("55 55 3321-4500", "5533214500"),
    ],
)
def test_ddd_55_is_not_confused_with_the_country_code(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(11) 3321-4500", "1133214500"),
        ("+55 11 3321-4500", "1133214500"),
        ("551133214500", "1133214500"),
    ],
)
def test_landline_with_ddd_is_accepted(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "+",
        "()",
        "91234-5678",
        "3321-4500",
        "+55 91234-5678",
        "+55",
        "55",
        "(11) 91234-567",
        "(11) 91234-56789",
        "(11) 81234-5678",
        "(01) 91234-5678",
        "(10) 91234-5678",
        "(11) 1321-4500",
        "(11) 9321-4500",
        "+1 415 555 2671",
        "+54 11 91234-5678",
        "54 11 91234-5678",
        "55 55 55 11 91234-5678",
        "++55 11 91234-5678",
        "11+912345678",
        "abc11912345678",
        "11912345678x",
        "telefone: 11912345678",
        "marina.teste@example.com",
        "١١٩١٢٣٤٥٦٧٨",
        FULLWIDTH_DIGITS,
        f"{NATIONAL_MOBILE}٣",
        f"{NATIONAL_MOBILE}{FULLWIDTH_DIGITS}",
    ],
)
def test_invalid_or_ddd_less_phones_return_none(raw):
    assert normalize_phone(raw) is None
