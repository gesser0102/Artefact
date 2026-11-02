from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from emporio_agent.domain.models import Category, Product, ProductStatus, Promotion


def make_category(category_id: int, name: str) -> Category:
    return Category(category_id=category_id, name=name, description=f"Categoria {name}")


def make_product(
    product_id: int,
    name: str,
    category_id: int,
    price: str,
    *,
    stock_quantity: int = 5,
    status: ProductStatus = ProductStatus.ACTIVE,
    description: str = "Instrumento musical",
    specs: dict[str, Any] | None = None,
) -> Product:
    return Product(
        product_id=product_id,
        name=name,
        category_id=category_id,
        description=description,
        price_brl=Decimal(price),
        stock_quantity=stock_quantity,
        status=status,
        specs={} if specs is None else specs,
        created_at=date(2024, 1, 1),
    )


def make_promotion(promotion_id: int, product_id: int, discount_percent: int) -> Promotion:
    return Promotion(
        promotion_id=promotion_id,
        product_id=product_id,
        discount_percent=discount_percent,
        description="Promoção de teste",
        is_active=True,
    )


@dataclass
class InMemoryCatalogRepository:
    categories: Iterable[Category] = ()
    products: Iterable[Product] = ()
    promotions: Iterable[Promotion] = ()
    _categories_by_id: dict[int, Category] = field(init=False)
    _products_by_id: dict[int, Product] = field(init=False)
    _promotions_by_product_id: dict[int, Promotion] = field(init=False)

    def __post_init__(self) -> None:
        self._categories_by_id = {item.category_id: item for item in self.categories}
        self._products_by_id = {item.product_id: item for item in self.products}
        self._promotions_by_product_id = {item.product_id: item for item in self.promotions}

    def list_categories(self) -> Sequence[Category]:
        return tuple(self._categories_by_id.values())

    def get_category(self, category_id: int) -> Category:
        return self._categories_by_id[category_id]

    def list_products(self) -> Sequence[Product]:
        return tuple(self._products_by_id.values())

    def get_product(self, product_id: int) -> Product | None:
        return self._products_by_id.get(product_id)

    def list_active_promotions(self) -> Sequence[Promotion]:
        return tuple(self._promotions_by_product_id.values())

    def get_active_promotion(self, product_id: int) -> Promotion | None:
        return self._promotions_by_product_id.get(product_id)


@dataclass
class RecordingErrorReporter:
    reports: list[tuple[str, Exception]] = field(default_factory=list)

    def __call__(self, scope: str, error: Exception, **context: Any) -> None:
        self.reports.append((scope, error))
