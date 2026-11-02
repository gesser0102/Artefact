from decimal import Decimal

import pytest

from emporio_agent.domain.pricing import format_brl, max_installments, quote_price


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("2199"), "R$ 2.199,00"),
        (Decimal("599.9"), "R$ 599,90"),
        (Decimal("12000"), "R$ 12.000,00"),
        (Decimal("1234567.895"), "R$ 1.234.567,90"),
        (Decimal("0.5"), "R$ 0,50"),
    ],
)
def test_format_brl_uses_brazilian_separators(value, expected):
    assert format_brl(value) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0.00", 1),
        ("90.00", 1),
        ("99.99", 1),
        ("100.00", 2),
        ("149.99", 2),
        ("150.00", 3),
        ("319.99", 3),
        ("320.00", 4),
        ("400.00", 5),
        ("479.99", 5),
        ("480.00", 6),
        ("599.90", 6),
        ("699.99", 6),
        ("700.00", 7),
        ("800.00", 8),
        ("1199.99", 11),
        ("1200.00", 12),
        ("1200.01", 12),
        ("50000.00", 12),
    ],
)
def test_max_installments_follows_section_3_1_tiers(amount, expected):
    assert max_installments(Decimal(amount)) == expected


def test_section_3_1_prevails_over_section_3_flat_minimum():
    assert max_installments(Decimal("320.00")) == 4


def test_quote_without_promotion_offers_pix_on_list_price():
    quote = quote_price(Decimal("2199"), None)

    assert quote.list_price == Decimal("2199.00")
    assert quote.discount_percent is None
    assert quote.final_price == Decimal("2199.00")
    assert quote.pix_price == Decimal("2089.05")
    assert quote.max_installments == 12
    assert quote.installment_amount == Decimal("183.25")


def test_quote_with_promotion_never_accumulates_pix():
    quote = quote_price(Decimal("359"), 10)

    assert quote.list_price == Decimal("359.00")
    assert quote.discount_percent == 10
    assert quote.final_price == Decimal("323.10")
    assert quote.pix_price is None
    assert quote.max_installments == 4
    assert quote.installment_amount == Decimal("80.78")


def test_installments_are_computed_on_discounted_price():
    assert quote_price(Decimal("1250"), None).max_installments == 12
    assert quote_price(Decimal("1250"), 20).max_installments == 10


def test_rounding_is_half_up():
    assert quote_price(Decimal("0.10"), None).pix_price == Decimal("0.10")
    assert quote_price(Decimal("10.10"), None).pix_price == Decimal("9.60")
    assert quote_price(Decimal("100.10"), 5).final_price == Decimal("95.10")
    assert quote_price(Decimal("0.50"), 1).final_price == Decimal("0.50")
    assert format_brl(Decimal("1.005")) == "R$ 1,01"
