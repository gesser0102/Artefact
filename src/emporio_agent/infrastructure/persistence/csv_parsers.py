import json
from datetime import date
from decimal import Decimal
from typing import Any

from emporio_agent.domain.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    Product,
    ProductStatus,
    Promotion,
)

ACTIVE_FLAGS = {"0": False, "1": True}


def required_text(row: dict[str, str], column: str) -> str:
    value = row[column]
    if not value or not value.strip():
        raise ValueError(f"empty column {column}")
    return value.strip()


def optional_text(row: dict[str, str], column: str) -> str | None:
    value = row[column]
    return value.strip() if value and value.strip() else None


def optional_date(row: dict[str, str], column: str) -> date | None:
    value = optional_text(row, column)
    return date.fromisoformat(value) if value else None


def parse_money(raw_value: str) -> Decimal:
    amount = Decimal(raw_value)
    if not amount.is_finite() or amount < 0:
        raise ValueError("money value out of range")
    return amount


def parse_specs(raw_value: str) -> dict[str, Any]:
    specs = json.loads(raw_value)
    if not isinstance(specs, dict):
        raise ValueError("specs is not a JSON object")
    return specs


def parse_category(row: dict[str, str]) -> Category:
    return Category(
        category_id=int(row["category_id"]),
        name=required_text(row, "name"),
        description=required_text(row, "description"),
    )


def parse_product(row: dict[str, str]) -> Product:
    return Product(
        product_id=int(row["product_id"]),
        name=required_text(row, "name"),
        category_id=int(row["category_id"]),
        description=required_text(row, "description"),
        price_brl=parse_money(row["price_brl"]),
        stock_quantity=int(row["stock_quantity"]),
        status=ProductStatus(row["status"]),
        specs=parse_specs(row["specs"]),
        created_at=date.fromisoformat(row["created_at"]),
    )


def parse_promotion(row: dict[str, str]) -> Promotion:
    return Promotion(
        promotion_id=int(row["promotion_id"]),
        product_id=int(row["product_id"]),
        discount_percent=int(row["discount_percent"]),
        description=required_text(row, "description"),
        is_active=ACTIVE_FLAGS[row["is_active"]],
    )


def parse_customer(row: dict[str, str]) -> Customer:
    return Customer(
        customer_id=int(row["customer_id"]),
        name=required_text(row, "name"),
        phone=required_text(row, "phone"),
        email=required_text(row, "email"),
        city=required_text(row, "city"),
    )


def parse_order(row: dict[str, str]) -> Order:
    return Order(
        order_id=int(row["order_id"]),
        customer_id=int(row["customer_id"]),
        order_date=date.fromisoformat(row["order_date"]),
        status=required_text(row, "status"),
        total_brl=parse_money(row["total_brl"]),
        payment_method=required_text(row, "payment_method"),
        tracking_code=optional_text(row, "tracking_code"),
        estimated_delivery=optional_date(row, "estimated_delivery"),
        notes=optional_text(row, "notes"),
    )


def parse_order_item(row: dict[str, str]) -> OrderItem:
    return OrderItem(
        order_id=int(row["order_id"]),
        product_id=int(row["product_id"]),
        quantity=int(row["quantity"]),
    )
