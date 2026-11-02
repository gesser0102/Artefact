from dataclasses import dataclass
from typing import Any

from emporio_agent.domain.availability import Availability
from emporio_agent.domain.pricing import PriceQuote


@dataclass(frozen=True)
class ProductSummary:
    product_id: int
    name: str
    category: str
    quote: PriceQuote
    availability: Availability
    stock_quantity: int


@dataclass(frozen=True)
class SearchResult:
    total_matches: int
    items: tuple[ProductSummary, ...]


@dataclass(frozen=True)
class ProductDetails:
    summary: ProductSummary
    details_reliable: bool
    description: str | None
    specs: dict[str, Any] | None
    alternatives: tuple[ProductSummary, ...] | None


@dataclass(frozen=True)
class AmbiguousProduct:
    total_matches: int
    matches: tuple[ProductSummary, ...]


type ProductLookup = ProductDetails | AmbiguousProduct | None


@dataclass(frozen=True)
class CategoryOverview:
    category_id: int
    name: str
    available_products: int


@dataclass(frozen=True)
class ActivePromotion:
    promotion_id: int
    product_id: int
    name: str
    description: str
    quote: PriceQuote
    availability: Availability
