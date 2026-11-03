from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Protocol

from emporio_agent.application.conversation.messages import ChatCompletion, ChatMessage, ToolSpec
from emporio_agent.domain.models import Category, Customer, Order, OrderItem, Product, Promotion
from emporio_agent.domain.policies import PolicySection


class CatalogRepository(Protocol):
    def list_categories(self) -> Sequence[Category]: ...

    def get_category(self, category_id: int) -> Category: ...

    def list_products(self) -> Sequence[Product]: ...

    def get_product(self, product_id: int) -> Product | None: ...

    def list_active_promotions(self) -> Sequence[Promotion]: ...

    def get_active_promotion(self, product_id: int) -> Promotion | None: ...


class OrderRepository(Protocol):
    def get_order(self, order_id: int) -> Order | None: ...

    def get_customer(self, customer_id: int) -> Customer | None: ...

    def list_order_items(self, order_id: int) -> Sequence[OrderItem]: ...


class PolicyRepository(Protocol):
    def list_sections(self) -> Sequence[PolicySection]: ...


class Clock(Protocol):
    def today(self) -> date: ...

    def now(self) -> datetime: ...


class ErrorReporter(Protocol):
    def __call__(self, scope: str, error: Exception, **context: Any) -> None: ...


class ChatModel(Protocol):
    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool = True,
    ) -> ChatCompletion: ...


class TraceSink(Protocol):
    def write(self, record: Mapping[str, Any]) -> None: ...
