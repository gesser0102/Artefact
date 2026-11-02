from enum import StrEnum

from emporio_agent.domain.models import Product, ProductStatus


class Availability(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


def availability_of(product: Product) -> Availability:
    if product.status is ProductStatus.DISCONTINUED:
        return Availability.DISCONTINUED
    if product.status is ProductStatus.COMING_SOON:
        return Availability.COMING_SOON
    return Availability.AVAILABLE if product.stock_quantity > 0 else Availability.OUT_OF_STOCK
