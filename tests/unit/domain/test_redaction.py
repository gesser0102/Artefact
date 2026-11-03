import time

import pytest

from emporio_agent.domain.redaction import REDACTED, is_sensitive_key, redact_text

LONG_DIGIT_RUN = "9" * 20000
LONG_RUN_TIME_LIMIT_SECONDS = 0.5
REALISTIC_REPETITIONS = 6
REALISTIC_SENTENCE = (
    "Pedido 12 de R$ 1.299,00 em 12x de R$ 108,25, rastreio BRAB1234567BR, "
    "entregue em 2026-02-28 (28/02/2026), CEP 79002-000, desconto 10%. "
)
REALISTIC_PHONES = ("(67) 99999-0000", "67 9 8888 7777", "+55 67 3341-4444", "11912345678")

MOBILE_FORMATS = [
    "(67) 99999-0000",
    "67999990000",
    "+55 67 99999-0000",
    "55 67 99999-0000",
    "+5567999990000",
    "67 9 9999 0000",
    "(67) 9 9999-0000",
    "67-9-9999-0000",
    "67 99999.0000",
    "67.99999.0000",
    "+55 (67) 9 9999 0000",
]
LANDLINE_FORMATS = ["(67) 3341-4444", "6733414444", "67 3341 4444", "+55 67 3341-4444"]
HARMLESS_TEXTS = [
    "pedido 12",
    "pedido 9999",
    "R$ 1.127,00",
    "R$ 3.450,00",
    "R$ 108,25",
    "2026-02-28",
    "28/02/2026",
    "02/03",
    "CEP 79002-000",
    "BRAB1234567BR",
    "10%",
    "12x",
    "6x de R$ 100,00",
    "12x de R$ 108,25",
    "produto 95",
    "2026",
    "seção 4.1",
    "91234-5678",
    "(67) 99999-000",
    "(01) 99999-0000",
    "(67) 89999-0000",
    "Pedido 12 de R$ 1.299,00 em 12x de R$ 108,25, rastreio BRAB1234567BR",
    "Entregue em 2026-02-28, previsão 2026-03-04, total R$ 3.450,00.",
]


@pytest.mark.parametrize("phone", [*MOBILE_FORMATS, *LANDLINE_FORMATS])
def test_every_accepted_phone_format_is_redacted_whole(phone):
    assert redact_text(f"meu fone {phone} fim") == f"meu fone {REDACTED} fim"
    assert redact_text(phone) == REDACTED


@pytest.mark.parametrize("text", HARMLESS_TEXTS)
def test_ordinary_numbers_are_kept(text):
    assert redact_text(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pedido 7 (67) 99999-0000", f"pedido 7 {REDACTED}"),
        ("7 67999990000", f"7 {REDACTED}"),
        ("2026-02-28 67 9 9999 0000", f"2026-02-28 {REDACTED}"),
        ("67999990000 2026-02-28", f"{REDACTED} 2026-02-28"),
        ("67999990000.0", f"{REDACTED}.0"),
        ("abc67999990000x", f"abc{REDACTED}x"),
        ("(67) 99999-0000 ou (67) 3341-4444", f"{REDACTED} ou {REDACTED}"),
        ("67999990000 67988887777", f"{REDACTED} {REDACTED}"),
    ],
)
def test_phones_next_to_other_numbers_are_still_redacted(text, expected):
    assert redact_text(text) == expected


def test_long_digit_run_is_redacted_in_linear_time_without_recursion():
    started = time.perf_counter()

    output = redact_text(LONG_DIGIT_RUN)

    assert time.perf_counter() - started < LONG_RUN_TIME_LIMIT_SECONDS
    assert REDACTED in output
    assert "9" * 10 not in output


def test_long_realistic_text_keeps_prices_and_redacts_every_phone():
    paragraphs = [
        f"{REALISTIC_SENTENCE}Contato do cliente: {phone}. " for phone in REALISTIC_PHONES
    ]
    text = "".join(paragraphs * REALISTIC_REPETITIONS)
    assert len(text) > 4000

    output = redact_text(text)

    assert output == "".join(
        [f"{REALISTIC_SENTENCE}Contato do cliente: {REDACTED}. " for _ in REALISTIC_PHONES]
        * REALISTIC_REPETITIONS
    )
    assert output.count(REDACTED) == len(REALISTIC_PHONES) * REALISTIC_REPETITIONS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mande para joana.prado@example.com hoje", f"mande para {REDACTED} hoje"),
        ("JOANA+loja@sub.example.com.br", REDACTED),
        ("chave gsk_abc123DEF", f"chave {REDACTED}"),
        (
            "contato lucas@jmail.com (67) 99812-3456 gsk_x",
            f"contato {REDACTED} {REDACTED} {REDACTED}",
        ),
    ],
)
def test_emails_and_api_keys_are_redacted(text, expected):
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    ("key", "sensitive"),
    [
        ("phone", True),
        ("Telefone", True),
        ("customer_email", True),
        ("GROQ_API_KEY", True),
        ("order_id", False),
        ("query", False),
    ],
)
def test_sensitive_keys(key, sensitive):
    assert is_sensitive_key(key) is sensitive
