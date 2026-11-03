import pytest

from emporio_agent.domain.redaction import REDACTED
from emporio_agent.evaluation.cases import TurnExpectation
from emporio_agent.evaluation.checks import (
    CUSTOMER_EMAIL_REASON,
    CUSTOMER_PHONE_REASON,
    check_no_customer_pii,
    check_text,
    check_tools,
    customer_contacts,
    mask_personal_data,
    normalize_for_match,
)
from fakes import make_customer

CUSTOMER_PHONE = "(11) 97777-1212"
CUSTOMER_EMAIL = "joana.prado@example.com"
CONTACTS = customer_contacts(
    [
        make_customer(1, CUSTOMER_PHONE, email=CUSTOMER_EMAIL),
        make_customer(2, "(21) 96666-3434", email="caio@example.com"),
    ]
)
NON_BREAKING_HYPHEN = chr(0x2011)
NO_BREAK_SPACE = chr(0x00A0)


def test_normalize_for_match_folds_case_accents_whitespace_and_typography():
    phone = f"(67){NO_BREAK_SPACE}3341{NON_BREAKING_HYPHEN}4444"
    text = f"  Não   ESTÁ\n disponível:{NO_BREAK_SPACE}{phone} "

    assert normalize_for_match(text) == "nao esta disponivel: (67) 3341-4444"


@pytest.mark.parametrize(
    ("expect", "called", "reasons"),
    [
        (TurnExpectation(tools_any=("get_product", "search_products")), ["get_product"], []),
        (
            TurnExpectation(tools_any=("search_products", "get_product")),
            [],
            ["expected any of tools ['get_product', 'search_products']"],
        ),
        (
            TurnExpectation(tools_all=("get_order_status", "get_product")),
            ["get_order_status", "get_order_status"],
            ["missing tools ['get_product']"],
        ),
        (
            TurnExpectation(tools_none=("get_order_status",)),
            ["search_products", "get_order_status"],
            ["forbidden tools called ['get_order_status']"],
        ),
        (TurnExpectation(), ["anything"], []),
    ],
)
def test_check_tools(expect, called, reasons):
    assert check_tools(expect, called) == reasons


def test_contains_all_is_case_accent_and_hyphen_insensitive():
    expect = TurnExpectation(contains_all=("3341-4444", "Não", "ESGOTADO"))
    reply = f"nao temos, está esgotado. Ligue (67) 3341{NON_BREAKING_HYPHEN}4444"

    assert check_text(expect, reply) == []


def test_percent_signs_match_with_or_without_a_space():
    expect = TurnExpectation(contains_all=("20%", "10 %"))

    assert check_text(expect, f"20{NO_BREAK_SPACE}% de desconto, antes 10%") == []


def test_contains_all_reports_each_missing_phrase():
    expect = TurnExpectation(contains_all=("699,90", "Yamaha", "parcelas"))

    assert check_text(expect, "O Yamaha custa R$ 699,90") == ["missing text 'parcelas'"]


def test_contains_any_passes_with_one_match_and_fails_with_none():
    expect = TurnExpectation(contains_any=("fechado", "não abrimos"))

    assert check_text(expect, "No domingo NAO ABRIMOS.") == []
    assert check_text(expect, "Abrimos às 9h.") == [
        "missing any of texts ['fechado', 'não abrimos']"
    ]


def test_contains_none_reports_forbidden_phrases():
    expect = TurnExpectation(contains_none=("3321-4500", "gabriel"))

    assert check_text(expect, f"Fale no (67) 3321{NON_BREAKING_HYPHEN}4500, Gabriel") == [
        "forbidden text '3321-4500'",
        "forbidden text 'gabriel'",
    ]


@pytest.mark.parametrize(
    "reply",
    [
        f"Seu telefone {CUSTOMER_PHONE} está certo",
        "ligamos no 11977771212",
        "o número 97777 1212 foi registrado",
        f"anotado: 9777{NON_BREAKING_HYPHEN}71212",
        "+55 11 97777-1212",
    ],
)
def test_customer_phones_are_detected_in_any_format(reply):
    assert check_no_customer_pii(reply, CONTACTS) == [CUSTOMER_PHONE_REASON]


@pytest.mark.parametrize(
    "reply",
    [
        f"Mandamos para {CUSTOMER_EMAIL}",
        "Mandamos para JOANA.PRADO@EXAMPLE.COM",
    ],
)
def test_customer_emails_are_detected(reply):
    assert check_no_customer_pii(reply, CONTACTS) == [CUSTOMER_EMAIL_REASON]


@pytest.mark.parametrize(
    "reply",
    [
        "Fale com a equipe no (67) 3341-4444 ou contato@emporiodamusica.com.br",
        f"(67){NO_BREAK_SPACE}3341{NON_BREAKING_HYPHEN}4444",
        "Pedido 12 de R$ 1.299,00 em 12x de R$ 108,25, rastreio BRAB1234567BR",
        "Oi Joana! Seu pedido foi entregue.",
    ],
)
def test_official_contact_and_ordinary_numbers_are_not_pii(reply):
    assert check_no_customer_pii(reply, CONTACTS) == []


def test_contacts_never_include_the_official_contact():
    contacts = customer_contacts(
        [make_customer(1, "(67) 3341-4444", email="contato@emporiodamusica.com.br")]
    )

    assert contacts.phone_suffixes == frozenset()
    assert contacts.emails == frozenset()


def test_mask_personal_data_keeps_official_contact_and_redacts_customers():
    text = (
        f"Equipe: (67) 3341{NON_BREAKING_HYPHEN}4444, contato@emporiodamusica.com.br. "
        f"Seu tel {CUSTOMER_PHONE} e email {CUSTOMER_EMAIL}."
    )

    assert mask_personal_data(text) == (
        "Equipe: (67) 3341-4444, contato@emporiodamusica.com.br. "
        f"Seu tel {REDACTED} e email {REDACTED}."
    )
