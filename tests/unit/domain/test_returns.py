from datetime import date, timedelta

import pytest

from emporio_agent.domain.exceptions import InvalidReceivedOnError
from emporio_agent.domain.models import OrderStatus
from emporio_agent.domain.returns import (
    DEFECT_DAYS_FROM_ORDER_DATE,
    LEGAL_WARRANTY_DAYS_FROM_RECEIPT,
    PREFERENCE_DAYS_ASSUMED_FROM_RECEIPT,
    REGRET_DAYS_FROM_RECEIPT,
    MissingInformation,
    NextStep,
    PurchaseChannel,
    ReturnOutcome,
    ReturnReason,
    ReturnRequirement,
    assess_return,
)
from fakes import make_order

ORDER_DATE = date(2026, 1, 1)
RECEIVED_ON = date(2026, 1, 10)


def delivered_order():
    return make_order(1, 1, OrderStatus.DELIVERED, order_date=ORDER_DATE)


def order_with(status):
    return make_order(1, 1, status, order_date=ORDER_DATE)


def test_deadlines_match_the_manual():
    assert REGRET_DAYS_FROM_RECEIPT == 7
    assert PREFERENCE_DAYS_ASSUMED_FROM_RECEIPT == 7
    assert DEFECT_DAYS_FROM_ORDER_DATE == 30
    assert LEGAL_WARRANTY_DAYS_FROM_RECEIPT == 90


def test_regret_without_data_asks_for_received_on_and_channel():
    result = assess_return(delivered_order(), ReturnReason.REGRET, RECEIVED_ON)

    assert result.outcome is ReturnOutcome.NEEDS_INFORMATION
    assert result.missing_information == (
        MissingInformation.RECEIVED_ON,
        MissingInformation.CHANNEL,
    )
    assert result.next_step is NextStep.PROVIDE_INFORMATION
    assert result.policy_section == "4.1"
    assert result.deadline is None


def test_regret_online_without_received_on_asks_only_for_received_on():
    result = assess_return(
        delivered_order(), ReturnReason.REGRET, RECEIVED_ON, PurchaseChannel.ONLINE
    )

    assert result.missing_information == (MissingInformation.RECEIVED_ON,)


def test_regret_with_received_on_without_channel_asks_only_for_channel():
    result = assess_return(
        delivered_order(), ReturnReason.REGRET, RECEIVED_ON, received_on=RECEIVED_ON
    )

    assert result.missing_information == (MissingInformation.CHANNEL,)


@pytest.mark.parametrize(
    ("days_after_receipt", "outcome", "next_step"),
    [
        (0, ReturnOutcome.ELIGIBLE, NextStep.REQUEST_RETURN),
        (6, ReturnOutcome.ELIGIBLE, NextStep.REQUEST_RETURN),
        (7, ReturnOutcome.ELIGIBLE, NextStep.REQUEST_RETURN),
        (8, ReturnOutcome.NOT_ELIGIBLE, NextStep.NO_FURTHER_ACTION),
    ],
)
def test_online_regret_counts_seven_days_from_receipt(days_after_receipt, outcome, next_step):
    result = assess_return(
        delivered_order(),
        ReturnReason.REGRET,
        RECEIVED_ON + timedelta(days=days_after_receipt),
        PurchaseChannel.ONLINE,
        RECEIVED_ON,
    )

    assert result.outcome is outcome
    assert result.next_step is next_step
    assert result.deadline == RECEIVED_ON + timedelta(days=7)
    assert result.policy_section == "4.1"


@pytest.mark.parametrize("received_on", [None, RECEIVED_ON])
def test_in_store_regret_is_not_eligible_and_points_to_preference(received_on):
    result = assess_return(
        delivered_order(),
        ReturnReason.REGRET,
        RECEIVED_ON,
        PurchaseChannel.IN_STORE,
        received_on,
    )

    assert result.outcome is ReturnOutcome.NOT_ELIGIBLE
    assert result.next_step is NextStep.CONSIDER_PREFERENCE_EXCHANGE
    assert result.missing_information == ()
    assert result.policy_section == "4.1"
    assert result.deadline is None


@pytest.mark.parametrize(
    ("days_after_receipt", "outcome", "next_step"),
    [
        (7, ReturnOutcome.ELIGIBLE, NextStep.REQUEST_EXCHANGE),
        (8, ReturnOutcome.NOT_ELIGIBLE, NextStep.NO_FURTHER_ACTION),
    ],
)
def test_preference_counts_seven_days_from_receipt(days_after_receipt, outcome, next_step):
    result = assess_return(
        delivered_order(),
        ReturnReason.PREFERENCE,
        RECEIVED_ON + timedelta(days=days_after_receipt),
        received_on=RECEIVED_ON,
    )

    assert result.outcome is outcome
    assert result.next_step is next_step
    assert result.policy_section == "4.3"


def test_preference_requires_received_on_but_not_channel():
    result = assess_return(delivered_order(), ReturnReason.PREFERENCE, RECEIVED_ON)

    assert result.outcome is ReturnOutcome.NEEDS_INFORMATION
    assert result.missing_information == (MissingInformation.RECEIVED_ON,)


def test_defect_on_day_30_from_the_order_is_eligible_without_received_on():
    result = assess_return(delivered_order(), ReturnReason.DEFECT, ORDER_DATE + timedelta(days=30))

    assert result.outcome is ReturnOutcome.ELIGIBLE
    assert result.next_step is NextStep.REQUEST_EXCHANGE
    assert result.deadline == ORDER_DATE + timedelta(days=30)
    assert result.policy_section == "4.2"
    assert result.legal_warranty_note is None


def test_defect_on_day_31_without_received_on_asks_for_it():
    result = assess_return(delivered_order(), ReturnReason.DEFECT, ORDER_DATE + timedelta(days=31))

    assert result.outcome is ReturnOutcome.NEEDS_INFORMATION
    assert result.missing_information == (MissingInformation.RECEIVED_ON,)
    assert result.next_step is NextStep.PROVIDE_INFORMATION


def test_defect_on_last_day_of_legal_warranty_goes_to_the_team():
    result = assess_return(
        delivered_order(),
        ReturnReason.DEFECT,
        RECEIVED_ON + timedelta(days=90),
        received_on=RECEIVED_ON,
    )

    assert result.outcome is ReturnOutcome.HUMAN_REQUIRED
    assert result.next_step is NextStep.HUMAN_HANDOFF
    assert result.deadline == ORDER_DATE + timedelta(days=30)
    assert result.legal_warranty_note is not None


def test_defect_after_legal_warranty_goes_to_manufacturer_warranty():
    result = assess_return(
        delivered_order(),
        ReturnReason.DEFECT,
        RECEIVED_ON + timedelta(days=91),
        received_on=RECEIVED_ON,
    )

    assert result.outcome is ReturnOutcome.NOT_ELIGIBLE
    assert result.next_step is NextStep.MANUFACTURER_WARRANTY
    assert result.deadline == ORDER_DATE + timedelta(days=30)
    assert result.legal_warranty_note is not None


def test_defect_window_ignores_received_on():
    late_receipt = ORDER_DATE + timedelta(days=25)

    result = assess_return(
        delivered_order(),
        ReturnReason.DEFECT,
        ORDER_DATE + timedelta(days=31),
        received_on=late_receipt,
    )

    assert result.outcome is ReturnOutcome.HUMAN_REQUIRED


def test_legal_warranty_note_cites_ninety_days_from_receipt_while_active():
    result = assess_return(
        delivered_order(),
        ReturnReason.DEFECT,
        RECEIVED_ON + timedelta(days=90),
        received_on=RECEIVED_ON,
    )

    assert result.legal_warranty_note is not None
    assert "90 dias" in result.legal_warranty_note
    assert "recebimento" in result.legal_warranty_note
    assert "10/04/2026" in result.legal_warranty_note
    assert "vale até" in result.legal_warranty_note


def test_legal_warranty_note_states_when_it_ended():
    result = assess_return(
        delivered_order(),
        ReturnReason.DEFECT,
        RECEIVED_ON + timedelta(days=91),
        received_on=RECEIVED_ON,
    )

    assert result.legal_warranty_note is not None
    assert "terminou em 10/04/2026" in result.legal_warranty_note


@pytest.mark.parametrize("reason", list(ReturnReason))
def test_cancelled_order_is_not_eligible_whatever_the_reason(reason):
    result = assess_return(order_with(OrderStatus.CANCELLED), reason, RECEIVED_ON)

    assert result.outcome is ReturnOutcome.NOT_ELIGIBLE
    assert result.missing_information == ()
    assert result.next_step is NextStep.NO_FURTHER_ACTION


@pytest.mark.parametrize("status", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
@pytest.mark.parametrize("reason", list(ReturnReason))
def test_order_awaiting_shipment_requires_a_human(status, reason):
    result = assess_return(order_with(status), reason, RECEIVED_ON)

    assert result.outcome is ReturnOutcome.HUMAN_REQUIRED
    assert result.next_step is NextStep.HUMAN_HANDOFF
    assert result.policy_section is None


@pytest.mark.parametrize(
    ("reason", "channel", "missing"),
    [
        (ReturnReason.DEFECT, None, (MissingInformation.RECEIVED_ON,)),
        (ReturnReason.PREFERENCE, None, (MissingInformation.RECEIVED_ON,)),
        (ReturnReason.REGRET, PurchaseChannel.ONLINE, (MissingInformation.RECEIVED_ON,)),
        (ReturnReason.REGRET, PurchaseChannel.IN_STORE, (MissingInformation.RECEIVED_ON,)),
        (
            ReturnReason.REGRET,
            None,
            (MissingInformation.RECEIVED_ON, MissingInformation.CHANNEL),
        ),
    ],
)
def test_shipped_order_needs_received_on(reason, channel, missing):
    result = assess_return(order_with(OrderStatus.SHIPPED), reason, RECEIVED_ON, channel)

    assert result.outcome is ReturnOutcome.NEEDS_INFORMATION
    assert result.missing_information == missing


def test_shipped_order_with_received_on_follows_the_rule():
    result = assess_return(
        order_with(OrderStatus.SHIPPED),
        ReturnReason.REGRET,
        RECEIVED_ON,
        PurchaseChannel.ONLINE,
        RECEIVED_ON,
    )

    assert result.outcome is ReturnOutcome.ELIGIBLE


@pytest.mark.parametrize(
    "received_on",
    [ORDER_DATE - timedelta(days=1), RECEIVED_ON + timedelta(days=1)],
)
@pytest.mark.parametrize("status", list(OrderStatus))
def test_received_on_outside_the_valid_range_is_rejected(received_on, status):
    with pytest.raises(InvalidReceivedOnError):
        assess_return(order_with(status), ReturnReason.REGRET, RECEIVED_ON, received_on=received_on)


@pytest.mark.parametrize("received_on", [ORDER_DATE, RECEIVED_ON])
def test_received_on_accepts_the_range_limits(received_on):
    result = assess_return(
        delivered_order(),
        ReturnReason.PREFERENCE,
        RECEIVED_ON,
        received_on=received_on,
    )

    assert result.outcome in {ReturnOutcome.ELIGIBLE, ReturnOutcome.NOT_ELIGIBLE}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            ReturnReason.REGRET,
            {
                ReturnRequirement.ORIGINAL_PACKAGING,
                ReturnRequirement.NO_SIGNS_OF_USE,
                ReturnRequirement.ALL_ACCESSORIES_AND_MANUALS,
            },
        ),
        (
            ReturnReason.DEFECT,
            {
                ReturnRequirement.MANUFACTURING_DEFECT,
                ReturnRequirement.NO_MISUSE_DAMAGE,
                ReturnRequirement.NO_UNAUTHORIZED_MODIFICATION,
                ReturnRequirement.NOT_CUSTOMIZED,
                ReturnRequirement.NOT_FINAL_SALE,
                ReturnRequirement.NOT_MOUTHPIECE,
            },
        ),
        (
            ReturnReason.PREFERENCE,
            {
                ReturnRequirement.DESIRED_PRODUCT_AVAILABLE,
                ReturnRequirement.PERFECT_CONDITION,
                ReturnRequirement.ORIGINAL_PACKAGING,
                ReturnRequirement.PRICE_DIFFERENCE_SETTLED,
                ReturnRequirement.NOT_CUSTOMIZED,
                ReturnRequirement.NOT_FINAL_SALE,
                ReturnRequirement.NOT_MOUTHPIECE,
            },
        ),
    ],
)
def test_requirements_of_the_applicable_section_are_always_listed(reason, expected):
    without_data = assess_return(delivered_order(), reason, RECEIVED_ON)
    with_data = assess_return(
        delivered_order(),
        reason,
        RECEIVED_ON + timedelta(days=60),
        PurchaseChannel.ONLINE,
        RECEIVED_ON,
    )

    assert set(without_data.requirements) == expected
    assert set(with_data.requirements) == expected


def test_return_enums_are_strings():
    assert ReturnReason.REGRET == "regret"
    assert PurchaseChannel.IN_STORE == "in_store"
    assert ReturnOutcome.NEEDS_INFORMATION == "needs_information"
    assert ReturnRequirement.ORIGINAL_PACKAGING == "original_packaging"
