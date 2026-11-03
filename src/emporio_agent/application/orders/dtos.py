from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from emporio_agent.domain.models import OrderStatus
from emporio_agent.domain.returns import ReturnAssessment


class FollowupReason(StrEnum):
    DELIVERY_OVERDUE = "delivery_overdue"
    PROCESSING_DELAYED = "processing_delayed"


@dataclass(frozen=True)
class NotVerified:
    pass


NOT_VERIFIED = NotVerified()


@dataclass(frozen=True)
class OrderItemLine:
    name: str
    quantity: int


@dataclass(frozen=True)
class VerifiedOrder:
    order_id: int
    customer_first_name: str
    status: OrderStatus
    order_date: date
    order_value: Decimal
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    items: tuple[OrderItemLine, ...]
    cancellation_note: str | None
    followup_reason: FollowupReason | None

    @property
    def requires_human_followup(self) -> bool:
        return self.followup_reason is not None


@dataclass(frozen=True)
class VerifiedReturnAssessment:
    order_id: int
    assessment: ReturnAssessment


type OrderLookup = VerifiedOrder | NotVerified
type ReturnLookup = VerifiedReturnAssessment | NotVerified
