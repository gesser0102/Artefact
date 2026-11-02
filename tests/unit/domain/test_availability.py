import pytest

from emporio_agent.domain.availability import Availability, availability_of
from emporio_agent.domain.models import ProductStatus
from fakes import make_product


def test_availability_enum_values_are_strings():
    assert {member.value for member in Availability} == {
        "available",
        "out_of_stock",
        "discontinued",
        "coming_soon",
    }


@pytest.mark.parametrize(
    ("status", "stock_quantity", "expected"),
    [
        (ProductStatus.ACTIVE, 1, Availability.AVAILABLE),
        (ProductStatus.ACTIVE, 0, Availability.OUT_OF_STOCK),
        (ProductStatus.DISCONTINUED, 5, Availability.DISCONTINUED),
        (ProductStatus.COMING_SOON, 2, Availability.COMING_SOON),
    ],
)
def test_availability_combines_status_and_stock(status, stock_quantity, expected):
    product = make_product(1, "Produto", 1, "10", status=status, stock_quantity=stock_quantity)

    assert availability_of(product) is expected
