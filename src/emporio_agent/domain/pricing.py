from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
ONE_HUNDRED_PERCENT = Decimal("100")
PIX_DISCOUNT_PERCENT = Decimal("5")
MAX_INSTALLMENTS = 12
MINIMUM_INSTALLMENT_BY_FIRST_COUNT = (
    (7, Decimal("100.00")),
    (4, Decimal("80.00")),
    (2, Decimal("50.00")),
)
BRL_SEPARATORS = str.maketrans({",": ".", ".": ","})


@dataclass(frozen=True)
class PriceQuote:
    list_price: Decimal
    discount_percent: int | None
    final_price: Decimal
    pix_price: Decimal | None
    max_installments: int
    installment_amount: Decimal


@dataclass(frozen=True)
class InstallmentOption:
    installments: int
    installment_amount: Decimal


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_brl(value: Decimal) -> str:
    return "R$ " + f"{round_money(value):,.2f}".translate(BRL_SEPARATORS)


def apply_discount(price: Decimal, discount_percent: Decimal) -> Decimal:
    return round_money(price * (ONE_HUNDRED_PERCENT - discount_percent) / ONE_HUNDRED_PERCENT)


def minimum_installment(installment_count: int) -> Decimal:
    return next(
        minimum
        for first_count, minimum in MINIMUM_INSTALLMENT_BY_FIRST_COUNT
        if installment_count >= first_count
    )


def max_installments(amount: Decimal) -> int:
    for installment_count in range(MAX_INSTALLMENTS, 1, -1):
        if amount >= minimum_installment(installment_count) * installment_count:
            return installment_count
    return 1


def installment_options(amount: Decimal) -> tuple[InstallmentOption, ...]:
    return tuple(
        InstallmentOption(
            installments=installment_count,
            installment_amount=round_money(amount / installment_count),
        )
        for installment_count in range(1, max_installments(amount) + 1)
    )


def quote_price(list_price: Decimal, discount_percent: int | None) -> PriceQuote:
    final_price = (
        apply_discount(list_price, Decimal(discount_percent))
        if discount_percent is not None
        else round_money(list_price)
    )
    installment_count = max_installments(final_price)
    return PriceQuote(
        list_price=round_money(list_price),
        discount_percent=discount_percent,
        final_price=final_price,
        pix_price=(
            None
            if discount_percent is not None
            else apply_discount(list_price, PIX_DISCOUNT_PERCENT)
        ),
        max_installments=installment_count,
        installment_amount=round_money(final_price / installment_count),
    )
