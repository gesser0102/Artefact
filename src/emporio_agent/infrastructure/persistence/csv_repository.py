import csv
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    Product,
    Promotion,
)
from emporio_agent.infrastructure.observability.logging import log_error
from emporio_agent.infrastructure.persistence.csv_parsers import (
    parse_category,
    parse_customer,
    parse_order,
    parse_order_item,
    parse_product,
    parse_promotion,
)

CSV_FILE_NAME_TEMPLATE = "desafio_tecnico_ai_eng - {table}.csv"
ROW_PARSING_ERRORS = (KeyError, TypeError, ValueError, ArithmeticError)


def read_rows(data_dir: Path, table: str) -> list[dict[str, str]]:
    path = data_dir / CSV_FILE_NAME_TEMPLATE.format(table=table)
    try:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        if not rows:
            raise ValueError("file has no records")
    except (OSError, csv.Error, ValueError) as error:
        log_error("store.read_rows", error, table=table)
        raise DataLoadError(f"Could not read table {table}") from error
    return rows


def load_table[Record](
    data_dir: Path,
    table: str,
    parse_row: Callable[[dict[str, str]], Record],
) -> list[Record]:
    records = []
    for row_number, row in enumerate(read_rows(data_dir, table), start=1):
        try:
            records.append(parse_row(row))
        except ROW_PARSING_ERRORS as error:
            log_error("store.load_table", error, table=table, row_number=row_number)
            raise DataLoadError(f"Could not parse row {row_number} of table {table}") from error
    return records


def index_by_id[Record](records: Sequence[Record], id_field: str) -> dict[int, Record]:
    index = {getattr(record, id_field): record for record in records}
    if len(index) != len(records):
        raise ValueError(f"duplicate {id_field}")
    return index


def require_references(
    relation: str,
    referenced_ids: Iterable[int],
    known_ids: Iterable[int],
) -> None:
    missing_ids = set(referenced_ids) - set(known_ids)
    if missing_ids:
        raise ValueError(f"{relation} references missing ids {sorted(missing_ids)}")


def group_items_by_order(items: Iterable[OrderItem]) -> dict[int, tuple[OrderItem, ...]]:
    grouped: defaultdict[int, list[OrderItem]] = defaultdict(list)
    for item in items:
        grouped[item.order_id].append(item)
    return {order_id: tuple(order_items) for order_id, order_items in grouped.items()}


@dataclass(frozen=True)
class CsvCatalogRepository:
    categories_by_id: dict[int, Category]
    products_by_id: dict[int, Product]
    promotions_by_id: dict[int, Promotion]
    active_promotions_by_product_id: dict[int, Promotion]
    customers_by_id: dict[int, Customer]
    orders_by_id: dict[int, Order]
    order_items_by_order_id: dict[int, tuple[OrderItem, ...]]

    @classmethod
    def load(cls, data_dir: Path) -> Self:
        categories = load_table(data_dir, "categories", parse_category)
        products = load_table(data_dir, "products", parse_product)
        promotions = load_table(data_dir, "promotions", parse_promotion)
        customers = load_table(data_dir, "customers", parse_customer)
        orders = load_table(data_dir, "orders", parse_order)
        order_items = load_table(data_dir, "order_items", parse_order_item)
        try:
            repository = cls(
                categories_by_id=index_by_id(categories, "category_id"),
                products_by_id=index_by_id(products, "product_id"),
                promotions_by_id=index_by_id(promotions, "promotion_id"),
                active_promotions_by_product_id=index_by_id(
                    [promotion for promotion in promotions if promotion.is_active],
                    "product_id",
                ),
                customers_by_id=index_by_id(customers, "customer_id"),
                orders_by_id=index_by_id(orders, "order_id"),
                order_items_by_order_id=group_items_by_order(order_items),
            )
            repository.validate_references()
        except ValueError as error:
            log_error("store.load", error)
            raise DataLoadError("Data files are inconsistent") from error
        return repository

    def validate_references(self) -> None:
        require_references(
            "products.category_id",
            (product.category_id for product in self.products_by_id.values()),
            self.categories_by_id,
        )
        require_references(
            "promotions.product_id",
            (promotion.product_id for promotion in self.promotions_by_id.values()),
            self.products_by_id,
        )
        require_references(
            "orders.customer_id",
            (order.customer_id for order in self.orders_by_id.values()),
            self.customers_by_id,
        )
        require_references(
            "order_items.order_id",
            self.order_items_by_order_id,
            self.orders_by_id,
        )
        require_references(
            "order_items.product_id",
            (item.product_id for items in self.order_items_by_order_id.values() for item in items),
            self.products_by_id,
        )

    def list_categories(self) -> Sequence[Category]:
        return tuple(self.categories_by_id.values())

    def get_category(self, category_id: int) -> Category:
        return self.categories_by_id[category_id]

    def list_products(self) -> Sequence[Product]:
        return tuple(self.products_by_id.values())

    def get_product(self, product_id: int) -> Product | None:
        return self.products_by_id.get(product_id)

    def list_active_promotions(self) -> Sequence[Promotion]:
        return tuple(self.active_promotions_by_product_id.values())

    def get_active_promotion(self, product_id: int) -> Promotion | None:
        return self.active_promotions_by_product_id.get(product_id)
