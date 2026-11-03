from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from emporio_agent.domain.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductStatus,
    Promotion,
)
from emporio_agent.domain.policies import PolicySection


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


def make_customer(
    customer_id: int,
    phone: str,
    *,
    name: str = "Marina Teste Sobrenome",
    email: str = "marina.teste@example.com",
    city: str = "Cidade Fictícia",
) -> Customer:
    return Customer(customer_id=customer_id, name=name, phone=phone, email=email, city=city)


def make_order(
    order_id: int,
    customer_id: int,
    status: OrderStatus = OrderStatus.DELIVERED,
    *,
    order_date: date = date(2026, 1, 1),
    total: str = "1000.00",
    payment_method: str = "pix",
    tracking_code: str | None = None,
    estimated_delivery: date | None = None,
    notes: str | None = None,
) -> Order:
    return Order(
        order_id=order_id,
        customer_id=customer_id,
        order_date=order_date,
        status=status,
        total_brl=Decimal(total),
        payment_method=payment_method,
        tracking_code=tracking_code,
        estimated_delivery=estimated_delivery,
        notes=notes,
    )


@dataclass
class InMemoryOrderRepository:
    orders: Iterable[Order] = ()
    customers: Iterable[Customer] = ()
    items: Iterable[OrderItem] = ()
    _orders_by_id: dict[int, Order] = field(init=False)
    _customers_by_id: dict[int, Customer] = field(init=False)

    def __post_init__(self) -> None:
        self._orders_by_id = {item.order_id: item for item in self.orders}
        self._customers_by_id = {item.customer_id: item for item in self.customers}
        self.items = tuple(self.items)

    def get_order(self, order_id: int) -> Order | None:
        return self._orders_by_id.get(order_id)

    def get_customer(self, customer_id: int) -> Customer | None:
        return self._customers_by_id.get(customer_id)

    def list_order_items(self, order_id: int) -> Sequence[OrderItem]:
        return tuple(item for item in self.items if item.order_id == order_id)


@dataclass
class FixedClock:
    current: date

    def today(self) -> date:
        return self.current


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


def make_section(
    section_id: str,
    title: str,
    body: str = "",
    *,
    parent: PolicySection | None = None,
) -> PolicySection:
    return PolicySection(
        section_id=section_id,
        title=title,
        parent_id=None if parent is None else parent.section_id,
        parent_title=None if parent is None else parent.title,
        body=body,
    )


@dataclass
class InMemoryPolicyRepository:
    sections: Iterable[PolicySection] = ()

    def __post_init__(self) -> None:
        self.sections = tuple(self.sections)

    def list_sections(self) -> Sequence[PolicySection]:
        return tuple(self.sections)


@dataclass
class RecordingErrorReporter:
    reports: list[tuple[str, Exception]] = field(default_factory=list)

    def __call__(self, scope: str, error: Exception, **context: Any) -> None:
        self.reports.append((scope, error))
