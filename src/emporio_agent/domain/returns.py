from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from emporio_agent.domain.exceptions import InvalidReceivedOnError
from emporio_agent.domain.models import AWAITING_SHIPMENT_STATUSES, Order, OrderStatus

REGRET_DAYS_FROM_RECEIPT = 7
PREFERENCE_DAYS_ASSUMED_FROM_RECEIPT = 7
DEFECT_DAYS_FROM_ORDER_DATE = 30
LEGAL_WARRANTY_DAYS_FROM_RECEIPT = 90
NOTE_DATE_FORMAT = "%d/%m/%Y"
LEGAL_WARRANTY_ACTIVE_NOTE = (
    "Garantia legal de {days} dias contados do recebimento: vale até {end}."
)
LEGAL_WARRANTY_ENDED_NOTE = (
    "Garantia legal de {days} dias contados do recebimento: terminou em {end}."
)


class ReturnReason(StrEnum):
    REGRET = "regret"
    DEFECT = "defect"
    PREFERENCE = "preference"


class PurchaseChannel(StrEnum):
    ONLINE = "online"
    IN_STORE = "in_store"


class ReturnOutcome(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEEDS_INFORMATION = "needs_information"
    HUMAN_REQUIRED = "human_required"


class MissingInformation(StrEnum):
    RECEIVED_ON = "received_on"
    CHANNEL = "channel"


class NextStep(StrEnum):
    REQUEST_RETURN = "request_return"
    REQUEST_EXCHANGE = "request_exchange"
    PROVIDE_INFORMATION = "provide_information"
    CONSIDER_PREFERENCE_EXCHANGE = "consider_preference_exchange"
    MANUFACTURER_WARRANTY = "manufacturer_warranty"
    HUMAN_HANDOFF = "human_handoff"
    NO_FURTHER_ACTION = "no_further_action"


class ReturnRequirement(StrEnum):
    ORIGINAL_PACKAGING = "original_packaging"
    NO_SIGNS_OF_USE = "no_signs_of_use"
    ALL_ACCESSORIES_AND_MANUALS = "all_accessories_and_manuals"
    MANUFACTURING_DEFECT = "manufacturing_defect"
    NO_MISUSE_DAMAGE = "no_misuse_damage"
    NO_UNAUTHORIZED_MODIFICATION = "no_unauthorized_modification"
    DESIRED_PRODUCT_AVAILABLE = "desired_product_available"
    PERFECT_CONDITION = "perfect_condition"
    PRICE_DIFFERENCE_SETTLED = "price_difference_settled"
    NOT_CUSTOMIZED = "not_customized"
    NOT_FINAL_SALE = "not_final_sale"
    NOT_MOUTHPIECE = "not_mouthpiece"


NON_EXCHANGEABLE_ITEM_REQUIREMENTS = (
    ReturnRequirement.NOT_CUSTOMIZED,
    ReturnRequirement.NOT_FINAL_SALE,
    ReturnRequirement.NOT_MOUTHPIECE,
)
REQUIREMENTS_BY_REASON = {
    ReturnReason.REGRET: (
        ReturnRequirement.ORIGINAL_PACKAGING,
        ReturnRequirement.NO_SIGNS_OF_USE,
        ReturnRequirement.ALL_ACCESSORIES_AND_MANUALS,
    ),
    ReturnReason.DEFECT: (
        ReturnRequirement.MANUFACTURING_DEFECT,
        ReturnRequirement.NO_MISUSE_DAMAGE,
        ReturnRequirement.NO_UNAUTHORIZED_MODIFICATION,
        *NON_EXCHANGEABLE_ITEM_REQUIREMENTS,
    ),
    ReturnReason.PREFERENCE: (
        ReturnRequirement.DESIRED_PRODUCT_AVAILABLE,
        ReturnRequirement.PERFECT_CONDITION,
        ReturnRequirement.ORIGINAL_PACKAGING,
        ReturnRequirement.PRICE_DIFFERENCE_SETTLED,
        *NON_EXCHANGEABLE_ITEM_REQUIREMENTS,
    ),
}
POLICY_SECTION_BY_REASON = {
    ReturnReason.REGRET: "4.1",
    ReturnReason.DEFECT: "4.2",
    ReturnReason.PREFERENCE: "4.3",
}


@dataclass(frozen=True)
class ReturnAssessment:
    outcome: ReturnOutcome
    missing_information: tuple[MissingInformation, ...]
    deadline: date | None
    policy_section: str | None
    next_step: NextStep
    requirements: tuple[ReturnRequirement, ...]
    legal_warranty_note: str | None


CANCELLED_ORDER_ASSESSMENT = ReturnAssessment(
    outcome=ReturnOutcome.NOT_ELIGIBLE,
    missing_information=(),
    deadline=None,
    policy_section=None,
    next_step=NextStep.NO_FURTHER_ACTION,
    requirements=(),
    legal_warranty_note=None,
)
AWAITING_SHIPMENT_ASSESSMENT = ReturnAssessment(
    outcome=ReturnOutcome.HUMAN_REQUIRED,
    missing_information=(),
    deadline=None,
    policy_section=None,
    next_step=NextStep.HUMAN_HANDOFF,
    requirements=(),
    legal_warranty_note=None,
)


def assessment_for(
    reason: ReturnReason,
    outcome: ReturnOutcome,
    next_step: NextStep,
    *,
    missing_information: tuple[MissingInformation, ...] = (),
    deadline: date | None = None,
    legal_warranty_note: str | None = None,
) -> ReturnAssessment:
    return ReturnAssessment(
        outcome=outcome,
        missing_information=missing_information,
        deadline=deadline,
        policy_section=POLICY_SECTION_BY_REASON[reason],
        next_step=next_step,
        requirements=REQUIREMENTS_BY_REASON[reason],
        legal_warranty_note=legal_warranty_note,
    )


def needs_information(
    reason: ReturnReason,
    *missing_information: MissingInformation,
) -> ReturnAssessment:
    return assessment_for(
        reason,
        ReturnOutcome.NEEDS_INFORMATION,
        NextStep.PROVIDE_INFORMATION,
        missing_information=missing_information,
    )


def require_valid_received_on(received_on: date | None, order_date: date, today: date) -> None:
    if received_on is not None and not order_date <= received_on <= today:
        raise InvalidReceivedOnError("received_on outside the order and current dates")


def legal_warranty_end(received_on: date) -> date:
    return received_on + timedelta(days=LEGAL_WARRANTY_DAYS_FROM_RECEIPT)


def legal_warranty_is_active(received_on: date, today: date) -> bool:
    return today <= legal_warranty_end(received_on)


def legal_warranty_note(received_on: date, today: date) -> str:
    warranty_end = legal_warranty_end(received_on)
    template = (
        LEGAL_WARRANTY_ACTIVE_NOTE
        if legal_warranty_is_active(received_on, today)
        else LEGAL_WARRANTY_ENDED_NOTE
    )
    return template.format(
        days=LEGAL_WARRANTY_DAYS_FROM_RECEIPT,
        end=warranty_end.strftime(NOTE_DATE_FORMAT),
    )


def assess_receipt_window(
    reason: ReturnReason,
    received_on: date,
    window_days: int,
    today: date,
    next_step_when_eligible: NextStep,
) -> ReturnAssessment:
    deadline = received_on + timedelta(days=window_days)
    if today <= deadline:
        return assessment_for(
            reason, ReturnOutcome.ELIGIBLE, next_step_when_eligible, deadline=deadline
        )
    return assessment_for(
        reason, ReturnOutcome.NOT_ELIGIBLE, NextStep.NO_FURTHER_ACTION, deadline=deadline
    )


def assess_regret(
    status: OrderStatus,
    channel: PurchaseChannel | None,
    received_on: date | None,
    today: date,
) -> ReturnAssessment:
    reason = ReturnReason.REGRET
    if channel is PurchaseChannel.IN_STORE and (
        received_on is not None or status is OrderStatus.DELIVERED
    ):
        return assessment_for(
            reason, ReturnOutcome.NOT_ELIGIBLE, NextStep.CONSIDER_PREFERENCE_EXCHANGE
        )
    if channel is None and received_on is None:
        return needs_information(reason, MissingInformation.RECEIVED_ON, MissingInformation.CHANNEL)
    if channel is None:
        return needs_information(reason, MissingInformation.CHANNEL)
    if received_on is None:
        return needs_information(reason, MissingInformation.RECEIVED_ON)
    return assess_receipt_window(
        reason, received_on, REGRET_DAYS_FROM_RECEIPT, today, NextStep.REQUEST_RETURN
    )


def assess_preference(received_on: date | None, today: date) -> ReturnAssessment:
    reason = ReturnReason.PREFERENCE
    if received_on is None:
        return needs_information(reason, MissingInformation.RECEIVED_ON)
    return assess_receipt_window(
        reason,
        received_on,
        PREFERENCE_DAYS_ASSUMED_FROM_RECEIPT,
        today,
        NextStep.REQUEST_EXCHANGE,
    )


def assess_defect(order: Order, received_on: date | None, today: date) -> ReturnAssessment:
    reason = ReturnReason.DEFECT
    if order.status is OrderStatus.SHIPPED and received_on is None:
        return needs_information(reason, MissingInformation.RECEIVED_ON)
    deadline = order.order_date + timedelta(days=DEFECT_DAYS_FROM_ORDER_DATE)
    if today <= deadline:
        return assessment_for(
            reason, ReturnOutcome.ELIGIBLE, NextStep.REQUEST_EXCHANGE, deadline=deadline
        )
    if received_on is None:
        return needs_information(reason, MissingInformation.RECEIVED_ON)
    if legal_warranty_is_active(received_on, today):
        return assessment_for(
            reason,
            ReturnOutcome.HUMAN_REQUIRED,
            NextStep.HUMAN_HANDOFF,
            deadline=deadline,
            legal_warranty_note=legal_warranty_note(received_on, today),
        )
    return assessment_for(
        reason,
        ReturnOutcome.NOT_ELIGIBLE,
        NextStep.MANUFACTURER_WARRANTY,
        deadline=deadline,
        legal_warranty_note=legal_warranty_note(received_on, today),
    )


def assess_return(
    order: Order,
    reason: ReturnReason,
    today: date,
    channel: PurchaseChannel | None = None,
    received_on: date | None = None,
) -> ReturnAssessment:
    require_valid_received_on(received_on, order.order_date, today)
    if order.status is OrderStatus.CANCELLED:
        return CANCELLED_ORDER_ASSESSMENT
    if order.status in AWAITING_SHIPMENT_STATUSES:
        return AWAITING_SHIPMENT_ASSESSMENT
    if reason is ReturnReason.DEFECT:
        return assess_defect(order, received_on, today)
    if reason is ReturnReason.REGRET:
        return assess_regret(order.status, channel, received_on, today)
    return assess_preference(received_on, today)
