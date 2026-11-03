from datetime import date, timedelta
from decimal import Decimal

import pytest

from emporio_agent.application.orders.dtos import (
    NOT_VERIFIED,
    FollowupReason,
    OrderItemLine,
    VerifiedOrder,
    VerifiedReturnAssessment,
)
from emporio_agent.application.orders.service import (
    ASSUMED_PROCESSING_FOLLOWUP_DAYS,
    OrderService,
)
from emporio_agent.domain.exceptions import InvalidReceivedOnError
from emporio_agent.domain.models import OrderItem, OrderStatus
from emporio_agent.domain.returns import PurchaseChannel, ReturnOutcome, ReturnReason
from fakes import (
    FixedClock,
    InMemoryCatalogRepository,
    InMemoryOrderRepository,
    make_customer,
    make_order,
    make_product,
)

TODAY = date(2026, 3, 1)
OWNER_PHONE = "(11) 91234-5678"
OTHER_PHONE = "(21) 98765-4321"


def service_for(*orders, items=(), customers=None, today=TODAY) -> OrderService:
    repository = InMemoryOrderRepository(
        orders=orders,
        customers=[
            make_customer(1, OWNER_PHONE, name="Marina Teste Sobrenome"),
            make_customer(2, OTHER_PHONE, name="Outro Cliente"),
        ]
        if customers is None
        else customers,
        items=items,
    )
    catalog = InMemoryCatalogRepository(products=[make_product(50, "Violão Fictício", 5, "900")])
    return OrderService(repository, catalog, FixedClock(today))


def test_verified_order_exposes_only_the_first_name_and_order_data():
    service = service_for(
        make_order(
            1,
            1,
            OrderStatus.SHIPPED,
            order_date=date(2026, 2, 20),
            total="3450",
            payment_method="credit_12x",
            tracking_code="BRAB1234567BR",
            estimated_delivery=date(2026, 3, 5),
        ),
        items=[OrderItem(order_id=1, product_id=50, quantity=2)],
    )

    assert service.find_verified_order(1, OWNER_PHONE) == VerifiedOrder(
        order_id=1,
        customer_first_name="Marina",
        status=OrderStatus.SHIPPED,
        order_date=date(2026, 2, 20),
        order_value=Decimal("3450"),
        payment_method="credit_12x",
        tracking_code="BRAB1234567BR",
        estimated_delivery=date(2026, 3, 5),
        items=(OrderItemLine(name="Violão Fictício", quantity=2),),
        cancellation_note=None,
        followup_reason=None,
    )


@pytest.mark.parametrize(
    "phone",
    ["(11) 91234-5678", "11912345678", "+55 11 91234-5678", "55 11 91234-5678"],
)
def test_every_accepted_phone_format_verifies_the_owner(phone):
    service = service_for(make_order(1, 1))

    assert isinstance(service.find_verified_order(1, phone), VerifiedOrder)


@pytest.mark.parametrize(
    ("order_id", "phone"),
    [
        (1, OTHER_PHONE),
        (9999, OWNER_PHONE),
        (1, "não sei"),
        (1, ""),
        (1, "   "),
        (9999, ""),
        (1, "91234-5678"),
        (1, "١١٩١٢٣٤٥٦٧٨"),
        (1, "marina.teste@example.com"),
    ],
)
def test_every_failure_is_the_same_not_verified(order_id, phone):
    service = service_for(make_order(1, 1))

    assert service.find_verified_order(order_id, phone) is NOT_VERIFIED
    assert service.assess_return(order_id, phone, ReturnReason.DEFECT) is NOT_VERIFIED


@pytest.mark.parametrize("registered_phone", ["", "sem telefone", "12345"])
def test_unusable_registered_phone_verifies_nobody(registered_phone):
    service = service_for(
        make_order(1, 1),
        customers=[make_customer(1, registered_phone)],
    )

    for phone in ("", "   ", "00000000000", OWNER_PHONE):
        assert service.find_verified_order(1, phone) is NOT_VERIFIED


def test_order_of_a_missing_customer_verifies_nobody():
    service = service_for(make_order(1, 99))

    assert service.find_verified_order(1, OWNER_PHONE) is NOT_VERIFIED
    assert service.find_verified_order(1, "") is NOT_VERIFIED


def test_gate_compares_phones_with_hmac_compare_digest(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "emporio_agent.application.orders.service.hmac.compare_digest",
        lambda left, right: calls.append((left, right)) or False,
    )
    service = service_for(make_order(1, 1))

    service.find_verified_order(1, OTHER_PHONE)
    service.find_verified_order(9999, OTHER_PHONE)
    service.find_verified_order(1, "inválido")

    assert len(calls) == 3


def test_missing_product_is_an_error_instead_of_a_hidden_item():
    service = service_for(
        make_order(1, 1),
        items=[OrderItem(order_id=1, product_id=404, quantity=1)],
    )

    with pytest.raises(LookupError):
        service.find_verified_order(1, OWNER_PHONE)


def test_cancellation_note_exists_only_for_cancelled_orders():
    service = service_for(
        make_order(1, 1, OrderStatus.CANCELLED, notes="Nota de cancelamento"),
        make_order(2, 1, OrderStatus.DELIVERED, notes="Nota interna"),
    )

    assert service.find_verified_order(1, OWNER_PHONE).cancellation_note == "Nota de cancelamento"
    assert service.find_verified_order(2, OWNER_PHONE).cancellation_note is None


@pytest.mark.parametrize(
    ("estimated_delivery", "expected"),
    [
        (TODAY - timedelta(days=1), FollowupReason.DELIVERY_OVERDUE),
        (TODAY, None),
        (TODAY + timedelta(days=1), None),
        (None, None),
    ],
)
def test_shipped_order_alerts_only_after_the_estimate(estimated_delivery, expected):
    service = service_for(
        make_order(
            1,
            1,
            OrderStatus.SHIPPED,
            order_date=date(2026, 1, 1),
            estimated_delivery=estimated_delivery,
        )
    )

    result = service.find_verified_order(1, OWNER_PHONE)

    assert result.followup_reason is expected
    assert result.requires_human_followup is (expected is not None)


@pytest.mark.parametrize("status", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
@pytest.mark.parametrize(
    ("age_in_days", "expected"),
    [
        (0, None),
        (ASSUMED_PROCESSING_FOLLOWUP_DAYS, None),
        (ASSUMED_PROCESSING_FOLLOWUP_DAYS + 1, FollowupReason.PROCESSING_DELAYED),
    ],
)
def test_processing_alert_starts_after_seven_days(status, age_in_days, expected):
    service = service_for(make_order(1, 1, status, order_date=TODAY - timedelta(days=age_in_days)))

    assert service.find_verified_order(1, OWNER_PHONE).followup_reason is expected


@pytest.mark.parametrize("status", [OrderStatus.DELIVERED, OrderStatus.CANCELLED])
def test_finished_orders_never_alert(status):
    service = service_for(
        make_order(1, 1, status, order_date=date(2020, 1, 1), estimated_delivery=date(2020, 1, 10))
    )

    result = service.find_verified_order(1, OWNER_PHONE)

    assert result.followup_reason is None
    assert result.requires_human_followup is False


def test_assess_return_uses_the_clock_and_the_domain_rule():
    received_on = date(2026, 2, 22)
    service = service_for(make_order(1, 1, order_date=date(2026, 2, 1)))

    result = service.assess_return(
        1, OWNER_PHONE, ReturnReason.REGRET, PurchaseChannel.ONLINE, received_on
    )

    assert isinstance(result, VerifiedReturnAssessment)
    assert result.order_id == 1
    assert result.assessment.outcome is ReturnOutcome.ELIGIBLE
    assert result.assessment.deadline == date(2026, 3, 1)


def test_assess_return_propagates_invalid_received_on_to_the_verified_owner():
    service = service_for(make_order(1, 1, order_date=date(2026, 2, 1)))

    with pytest.raises(InvalidReceivedOnError):
        service.assess_return(1, OWNER_PHONE, ReturnReason.REGRET, received_on=TODAY.replace(day=2))


def test_invalid_received_on_is_not_evaluated_before_the_gate():
    service = service_for(make_order(1, 1, order_date=date(2026, 2, 1)))

    result = service.assess_return(
        1, OTHER_PHONE, ReturnReason.REGRET, received_on=date(2020, 1, 1)
    )

    assert result is NOT_VERIFIED
