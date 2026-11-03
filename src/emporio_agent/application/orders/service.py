import hmac
from datetime import date, timedelta

from emporio_agent.application.orders.dtos import (
    NOT_VERIFIED,
    FollowupReason,
    OrderItemLine,
    OrderLookup,
    ReturnLookup,
    VerifiedOrder,
    VerifiedReturnAssessment,
)
from emporio_agent.application.ports import CatalogRepository, Clock, OrderRepository
from emporio_agent.domain.identity import normalize_phone
from emporio_agent.domain.models import AWAITING_SHIPMENT_STATUSES, Customer, Order, OrderStatus
from emporio_agent.domain.returns import PurchaseChannel, ReturnReason, assess_return

ASSUMED_PROCESSING_FOLLOWUP_DAYS = 7
UNMATCHABLE_PHONE = "00000000000"


def followup_reason_of(order: Order, today: date) -> FollowupReason | None:
    delivery_is_late = (
        order.status is OrderStatus.SHIPPED
        and order.estimated_delivery is not None
        and order.estimated_delivery < today
    )
    if delivery_is_late:
        return FollowupReason.DELIVERY_OVERDUE
    processing_limit = order.order_date + timedelta(days=ASSUMED_PROCESSING_FOLLOWUP_DAYS)
    if order.status in AWAITING_SHIPMENT_STATUSES and processing_limit < today:
        return FollowupReason.PROCESSING_DELAYED
    return None


class OrderService:
    def __init__(
        self,
        orders: OrderRepository,
        catalog: CatalogRepository,
        clock: Clock,
    ) -> None:
        self._orders = orders
        self._catalog = catalog
        self._clock = clock

    def find_verified_order(self, order_id: int, phone: str) -> OrderLookup:
        owned_order = self._find_owned_order(order_id, phone)
        if owned_order is None:
            return NOT_VERIFIED
        order, customer = owned_order
        return VerifiedOrder(
            order_id=order.order_id,
            customer_first_name=customer.name.split()[0],
            status=order.status,
            order_date=order.order_date,
            order_value=order.total_brl,
            payment_method=order.payment_method,
            tracking_code=order.tracking_code,
            estimated_delivery=order.estimated_delivery,
            items=self._item_lines_of(order),
            cancellation_note=order.notes if order.status is OrderStatus.CANCELLED else None,
            followup_reason=followup_reason_of(order, self._clock.today()),
        )

    def assess_return(
        self,
        order_id: int,
        phone: str,
        reason: ReturnReason,
        channel: PurchaseChannel | None = None,
        received_on: date | None = None,
    ) -> ReturnLookup:
        owned_order = self._find_owned_order(order_id, phone)
        if owned_order is None:
            return NOT_VERIFIED
        order, _ = owned_order
        return VerifiedReturnAssessment(
            order_id=order.order_id,
            assessment=assess_return(order, reason, self._clock.today(), channel, received_on),
        )

    def _find_owned_order(self, order_id: int, phone: str) -> tuple[Order, Customer] | None:
        order = self._orders.get_order(order_id)
        customer = None if order is None else self._orders.get_customer(order.customer_id)
        registered_phone = None if customer is None else normalize_phone(customer.phone)
        phone_matches = hmac.compare_digest(
            (normalize_phone(phone) or "").encode(),
            (registered_phone or UNMATCHABLE_PHONE).encode(),
        )
        if order is None or customer is None or not phone_matches:
            return None
        return order, customer

    def _item_lines_of(self, order: Order) -> tuple[OrderItemLine, ...]:
        lines = []
        for item in self._orders.list_order_items(order.order_id):
            product = self._catalog.get_product(item.product_id)
            if product is None:
                raise LookupError(f"order item references missing id {item.product_id}")
            lines.append(OrderItemLine(name=product.name, quantity=item.quantity))
        return tuple(lines)
