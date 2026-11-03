import json
import logging
import re
from datetime import date, timedelta

import pytest

from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.agent.tools.order_tools import assess_return_eligibility, get_order_status
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.domain.identity import normalize_phone
from emporio_agent.domain.pricing import format_brl
from emporio_agent.infrastructure.observability.logging import LOGGER_NAME, log_error, log_warning
from fakes import FixedClock, InMemoryPolicyRepository

TODAY = date(2026, 11, 2)
ORDER_IDS = range(1, 21)
PROCESSING_ORDER_IDS = range(9, 17)
DELIVERED_ORDER_IDS = range(1, 8)
CANCELLED_ORDER_IDS = range(17, 21)
NOT_VERIFIED_OUTPUT = '{"verified":false}'
NAME_PARTICLES = frozenset({"de", "da", "do", "dos", "das", "e"})
ORDER_OUTPUT_FIELDS = {
    "verified",
    "order_id",
    "customer_first_name",
    "status",
    "status_label",
    "order_date",
    "order_value",
    "payment_method_label",
    "tracking_code",
    "estimated_delivery",
    "items",
    "requires_human_followup",
    "followup_reason",
}


def tools_on(repository, today: date) -> ToolContext:
    return ToolContext(
        catalog=CatalogService(repository),
        orders=OrderService(repository, repository, FixedClock(today)),
        policies=PolicyService(InMemoryPolicyRepository()),
        report_error=log_error,
        report_rejected_input=log_warning,
    )


@pytest.fixture
def tools_today(repository) -> ToolContext:
    return tools_on(repository, TODAY)


def owner_of(repository, order_id: int):
    return repository.get_customer(repository.get_order(order_id).customer_id)


def phone_of(repository, order_id: int) -> str:
    return owner_of(repository, order_id).phone


def digits_of(phone: str) -> str:
    return "".join(character for character in phone if character.isdigit())


def phone_variants(phone: str) -> tuple[str, ...]:
    digits = digits_of(phone)
    return (
        phone,
        digits,
        digits[2:],
        f"{digits[:2]} {digits[2:7]}-{digits[7:]}",
        f"{digits[2:7]}-{digits[7:]}",
    )


def sensitive_values_of(customer) -> tuple[str, ...]:
    surnames = [word for word in customer.name.split()[1:] if word.casefold() not in NAME_PARTICLES]
    return (*phone_variants(customer.phone), customer.email, customer.city, *surnames)


def contains_word(text: str, value: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE) is not None


def test_every_registered_phone_normalizes(repository):
    for customer_id in range(1, 51):
        customer = repository.get_customer(customer_id)

        assert normalize_phone(customer.phone) == digits_of(customer.phone)


def test_order_1_is_verified_in_every_phone_format_with_the_right_items(repository, tools_today):
    digits = digits_of(phone_of(repository, 1))
    formats = [
        phone_of(repository, 1),
        digits,
        f"+55 {digits[:2]} {digits[2:7]}-{digits[7:]}",
        f"55 {digits[:2]} {digits[2:7]}-{digits[7:]}",
    ]
    [item] = repository.list_order_items(1)

    for phone in formats:
        result = json.loads(get_order_status(tools_today, {"order_id": 1, "phone": phone}))

        assert result["verified"] is True
        assert result["order_id"] == 1
        assert result["customer_first_name"] == owner_of(repository, 1).name.split()[0]
        assert result["items"] == [
            {"name": repository.get_product(item.product_id).name, "quantity": item.quantity}
        ]


def test_failures_are_byte_identical_on_real_data(repository, tools_today):
    owner_phone = phone_of(repository, 1)
    other_customer_phone = phone_of(repository, 2)
    assert owner_of(repository, 1).customer_id != owner_of(repository, 2).customer_id

    outputs = {
        get_order_status(tools_today, {"order_id": 1, "phone": other_customer_phone}),
        get_order_status(tools_today, {"order_id": 9999, "phone": owner_phone}),
        get_order_status(tools_today, {"order_id": 1, "phone": "telefone inválido"}),
        get_order_status(tools_today, {"order_id": 1, "phone": ""}),
    }

    assert outputs == {NOT_VERIFIED_OUTPUT}


def test_phone_of_the_same_customer_opens_all_their_orders(repository, tools_today):
    phone = phone_of(repository, 1)
    assert owner_of(repository, 19).customer_id == owner_of(repository, 1).customer_id

    assert json.loads(get_order_status(tools_today, {"order_id": 19, "phone": phone}))["verified"]


def test_shared_email_does_not_identify_customer_11_or_43(repository, tools_today):
    customer_11 = repository.get_customer(11)
    customer_43 = repository.get_customer(43)
    assert customer_11.email == customer_43.email
    assert customer_11.phone != customer_43.phone

    by_email = get_order_status(tools_today, {"order_id": 10, "email": customer_11.email})
    by_email_as_phone = get_order_status(tools_today, {"order_id": 10, "phone": customer_11.email})
    by_namesake = get_order_status(tools_today, {"order_id": 10, "phone": customer_43.phone})

    assert {by_email_as_phone, by_namesake} == {NOT_VERIFIED_OUTPUT}
    assert json.loads(by_email)["error"] == "invalid_arguments"
    assert customer_11.email not in by_email


@pytest.mark.parametrize("order_id", ORDER_IDS)
def test_no_order_output_reveals_customer_data(order_id, repository, tools_today):
    customer = owner_of(repository, order_id)
    arguments = {"order_id": order_id, "phone": customer.phone}
    status_output = get_order_status(tools_today, arguments)
    assessment_output = assess_return_eligibility(tools_today, {**arguments, "reason": "defect"})

    assert json.loads(status_output)["verified"] is True
    for output in (status_output, assessment_output):
        assert "customer_id" not in output
        for value in sensitive_values_of(customer):
            assert not contains_word(output, value)


@pytest.mark.parametrize("order_id", ORDER_IDS)
def test_order_output_has_exactly_the_contract_keys(order_id, repository, tools_today):
    result = json.loads(
        get_order_status(
            tools_today, {"order_id": order_id, "phone": phone_of(repository, order_id)}
        )
    )

    expected = ORDER_OUTPUT_FIELDS | (
        {"cancellation_note"} if order_id in CANCELLED_ORDER_IDS else set()
    )
    assert set(result) == expected


def status_of(repository, tools, order_id: int) -> dict[str, object]:
    return json.loads(
        get_order_status(tools, {"order_id": order_id, "phone": phone_of(repository, order_id)})
    )


def test_order_8_is_delivery_overdue(repository, tools_today):
    result = status_of(repository, tools_today, 8)

    assert result["status"] == "shipped"
    assert result["requires_human_followup"] is True
    assert result["followup_reason"] == "delivery_overdue"


@pytest.mark.parametrize("order_id", PROCESSING_ORDER_IDS)
def test_orders_9_to_16_are_processing_delayed(order_id, repository, tools_today):
    result = status_of(repository, tools_today, order_id)

    assert result["requires_human_followup"] is True
    assert result["followup_reason"] == "processing_delayed"


@pytest.mark.parametrize("order_id", [*DELIVERED_ORDER_IDS, *CANCELLED_ORDER_IDS])
def test_delivered_and_cancelled_orders_have_no_alert(order_id, repository, tools_today):
    result = status_of(repository, tools_today, order_id)

    assert result["requires_human_followup"] is False
    assert result["followup_reason"] is None


def test_order_17_has_cancellation_note(repository, tools_today):
    result = status_of(repository, tools_today, 17)

    assert result["cancellation_note"] == repository.get_order(17).notes


@pytest.mark.parametrize("order_id", ORDER_IDS)
def test_notes_reach_the_output_only_when_cancelled(order_id, repository, tools_today):
    result = status_of(repository, tools_today, order_id)

    assert ("cancellation_note" in result) is (order_id in CANCELLED_ORDER_IDS)


def test_order_3_value_is_order_value_and_never_paid_or_refund(repository, tools_today):
    output = get_order_status(tools_today, {"order_id": 3, "phone": phone_of(repository, 3)})
    result = json.loads(output)

    assert result["order_value"] == "R$ 3.450,00"
    assert result["order_value"] == format_brl(repository.get_order(3).total_brl)
    assert not any("paid" in key or "refund" in key for key in result)


@pytest.mark.parametrize("order_id", ORDER_IDS)
def test_no_output_has_paid_or_refund_keys(order_id, repository, tools_today):
    arguments = {"order_id": order_id, "phone": phone_of(repository, order_id)}
    outputs = [
        get_order_status(tools_today, arguments),
        assess_return_eligibility(tools_today, {**arguments, "reason": "regret"}),
    ]

    for output in outputs:
        assert "paid" not in output
        assert "refund" not in output


def assessment_for(repository, tools, order_id: int, **arguments: object) -> dict[str, object]:
    return json.loads(
        assess_return_eligibility(
            tools,
            {"order_id": order_id, "phone": phone_of(repository, order_id), **arguments},
        )
    )


def test_regret_without_data_needs_received_on_and_channel(repository, tools_today):
    result = assessment_for(repository, tools_today, 1, reason="regret")

    assert result["outcome"] == "needs_information"
    assert set(result["missing_information"]) == {"received_on", "channel"}


@pytest.mark.parametrize(("days_since_receipt", "outcome"), [(7, "eligible"), (8, "not_eligible")])
def test_online_regret_limit_on_a_delivered_order(days_since_receipt, outcome, repository):
    received_on = repository.get_order(1).estimated_delivery
    tools = tools_on(repository, received_on + timedelta(days=days_since_receipt))

    result = assessment_for(
        repository,
        tools,
        1,
        reason="regret",
        channel="online",
        received_on=received_on.isoformat(),
    )

    assert result["outcome"] == outcome
    assert result["deadline"] == (received_on + timedelta(days=7)).isoformat()


def test_in_store_regret_is_not_eligible(repository, tools_today):
    result = assessment_for(repository, tools_today, 1, reason="regret", channel="in_store")

    assert result["outcome"] == "not_eligible"
    assert result["next_step"] == "consider_preference_exchange"


@pytest.mark.parametrize(
    ("days_since_order", "outcome", "next_step"),
    [
        (30, "eligible", "request_exchange"),
        (31, "needs_information", "provide_information"),
    ],
)
def test_defect_limit_on_a_delivered_order(days_since_order, outcome, next_step, repository):
    order_date = repository.get_order(1).order_date
    tools = tools_on(repository, order_date + timedelta(days=days_since_order))

    result = assessment_for(repository, tools, 1, reason="defect")

    assert result["outcome"] == outcome
    assert result["next_step"] == next_step


def test_pending_and_cancelled_orders(repository, tools_today):
    pending = assessment_for(repository, tools_today, 13, reason="defect")
    cancelled = assessment_for(repository, tools_today, 17, reason="defect")

    assert pending["outcome"] == "human_required"
    assert cancelled["outcome"] == "not_eligible"


def test_future_received_on_is_invalid_arguments(repository, tools_today):
    tomorrow = (TODAY + timedelta(days=1)).isoformat()

    result = assessment_for(repository, tools_today, 1, reason="defect", received_on=tomorrow)

    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == "received_on"


def test_assessment_goes_through_the_same_gate(repository, tools_today):
    other_phone = phone_of(repository, 2)

    outputs = {
        assess_return_eligibility(
            tools_today, {"order_id": 1, "phone": other_phone, "reason": "regret"}
        ),
        assess_return_eligibility(
            tools_today,
            {"order_id": 9999, "phone": phone_of(repository, 1), "reason": "regret"},
        ),
        assess_return_eligibility(tools_today, {"order_id": 1, "phone": "", "reason": "regret"}),
    }
    without_phone = json.loads(
        assess_return_eligibility(tools_today, {"order_id": 1, "reason": "regret"})
    )

    assert outputs == {NOT_VERIFIED_OUTPUT}
    assert without_phone == {
        "error": "invalid_arguments",
        "details": [{"field": "phone", "message": "Field required"}],
    }


@pytest.mark.parametrize("tool", [get_order_status, assess_return_eligibility])
def test_integer_phone_verifies_like_text(tool, repository, tools_today):
    digits = int(digits_of(phone_of(repository, 1)))

    result = json.loads(tool(tools_today, {"order_id": 1, "phone": digits, "reason": "defect"}))

    assert result["verified"] is True


def test_phone_never_reaches_the_log_nor_error_output(repository, tools_today, caplog):
    logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG)
    phone = phone_of(repository, 1)
    digits = digits_of(phone)
    international = f"+55{digits}"
    calls = [
        (get_order_status, {"order_id": "abc", "phone": phone}),
        (get_order_status, {"order_id": True, "phone": phone}),
        (get_order_status, {"order_id": 1, "phone": [phone]}),
        (get_order_status, {"order_id": "abc", "phone": int(digits)}),
        (get_order_status, {"order_id": 1, "phone": {"telefone": phone}}),
        (get_order_status, {"order_id": "abc", phone: phone}),
        (get_order_status, {"order_id": "abc", digits: True, international: True}),
        (get_order_status, [phone]),
        (get_order_status, phone),
        (assess_return_eligibility, {"order_id": "abc", "phone": phone}),
        (assess_return_eligibility, {"order_id": 1, "phone": phone, "reason": phone}),
        (assess_return_eligibility, {"order_id": 1, "phone": phone, "reason": 7, phone: True}),
        (assess_return_eligibility, {"order_id": 1, "phone": phone, "channel": phone}),
        (
            assess_return_eligibility,
            {"order_id": 1, "phone": phone, "reason": "defect", "received_on": phone},
        ),
        (
            assess_return_eligibility,
            {"order_id": 1, "phone": phone, "reason": "defect", "received_on": digits},
        ),
        (
            assess_return_eligibility,
            {"order_id": 1, "phone": phone, "reason": "defect", "received_on": "2099-01-01"},
        ),
    ]

    outputs = [tool(tools_today, arguments) for tool, arguments in calls]

    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == len(calls)
    assert all(json.loads(output)["error"] == "invalid_arguments" for output in outputs)
    for value in (*phone_variants(phone), international):
        assert value not in caplog.text
        assert all(value not in output for output in outputs)
