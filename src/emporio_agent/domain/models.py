from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ProductStatus(StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


AWAITING_SHIPMENT_STATUSES = frozenset({OrderStatus.PENDING, OrderStatus.CONFIRMED})


@dataclass(frozen=True)
class Category:
    category_id: int
    name: str
    description: str


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    category_id: int
    description: str
    price_brl: Decimal
    stock_quantity: int
    status: ProductStatus
    specs: dict[str, Any]
    created_at: date


@dataclass(frozen=True)
class Promotion:
    promotion_id: int
    product_id: int
    discount_percent: int
    description: str
    is_active: bool


@dataclass(frozen=True)
class Customer:
    customer_id: int
    name: str
    phone: str = field(repr=False)
    email: str = field(repr=False)
    city: str


@dataclass(frozen=True)
class Order:
    order_id: int
    customer_id: int
    order_date: date
    status: OrderStatus
    total_brl: Decimal
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None


@dataclass(frozen=True)
class OrderItem:
    order_id: int
    product_id: int
    quantity: int
