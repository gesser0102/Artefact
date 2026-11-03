import json
from datetime import date

import pytest
from pydantic import ValidationError

from emporio_agent.agent.tools.catalog_tools import (
    get_product,
    list_active_promotions,
    list_categories,
    quote_installments,
    search_products,
)
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.agent.tools.serialization import to_tool_json
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from fakes import (
    FixedClock,
    InMemoryCatalogRepository,
    InMemoryOrderRepository,
    InMemoryPolicyRepository,
    RecordingErrorReporter,
    make_category,
    make_product,
    make_promotion,
)

ALL_TOOLS = [
    search_products,
    get_product,
    list_categories,
    list_active_promotions,
    quote_installments,
]


@pytest.fixture
def reporter() -> RecordingErrorReporter:
    return RecordingErrorReporter()


@pytest.fixture
def context(reporter) -> ToolContext:
    repository = InMemoryCatalogRepository(
        categories=[make_category(5, "Violões")],
        products=[
            make_product(95, "Violão Takamine GD20", 5, "2199"),
            make_product(96, "Violão Yamaha", 5, "900"),
        ],
        promotions=[make_promotion(1, 96, 10)],
    )
    return ToolContext(
        catalog=CatalogService(repository),
        orders=OrderService(InMemoryOrderRepository(), repository, FixedClock(date(2026, 11, 2))),
        policies=PolicyService(InMemoryPolicyRepository()),
        report_error=reporter,
        report_rejected_input=reporter,
    )


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_every_tool_returns_compact_json_text(tool, context):
    output = tool(context)

    assert isinstance(output, str)
    assert output == to_tool_json(json.loads(output))


def test_search_coerces_llm_arguments(context):
    result = json.loads(
        search_products(context, {"category": "5", "max_price": "1000", "limit": "1"})
    )

    assert [item["product_id"] for item in result["items"]] == [96]


def test_get_product_coerces_text_id(context):
    assert json.loads(get_product(context, {"product_id": "95"}))["product_id"] == 95


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        (search_products, {"max_price": "abc"}, "max_price"),
        (search_products, {"limit": 21}, "limit"),
        (search_products, {"category": True}, "category"),
        (search_products, {"brand": "Yamaha"}, "brand"),
        (get_product, {"product_id": "abc"}, "product_id"),
        (get_product, {"product_id": True}, "product_id"),
        (list_categories, {"extra": 1}, "extra"),
        (list_active_promotions, {"extra": 1}, "extra"),
    ],
)
def test_invalid_arguments_return_compact_error_and_report(
    tool, arguments, field, context, reporter
):
    output = tool(context, arguments)
    result = json.loads(output)

    assert set(result) == {"error", "details"}
    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == field
    assert set(result["details"][0]) == {"field", "message"}
    assert ": " not in output
    assert len(output) < 200
    [(scope, error)] = reporter.reports
    assert scope == f"tools.{tool.__name__}"
    assert isinstance(error, ValidationError)


@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize("arguments", [[], "texto", 7])
def test_non_object_arguments_do_not_raise(tool, arguments, context, reporter):
    result = json.loads(tool(context, arguments))

    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == "arguments"
    assert len(reporter.reports) == 1


def test_invalid_arguments_never_echo_the_input(context, reporter):
    output = search_products(context, {"min_price": "lucas@jmail.com"})
    _, error = reporter.reports[0]

    assert "lucas" not in output
    assert "lucas" not in str(error)


@pytest.mark.parametrize(
    "arguments",
    [
        {"category": "²"},
        {"category": "0665"},
        {"category": "9" * 5000},
        {"query": "²"},
        {"max_price": "1e999999999999999999999"},
        {"min_price": "-1e-999999999999999999999"},
        {"limit": "9" * 5000},
    ],
)
def test_hostile_search_arguments_do_not_raise(arguments, context):
    assert isinstance(json.loads(search_products(context, arguments)), dict)


def test_quote_installments_returns_every_interest_free_option(context):
    result = json.loads(quote_installments(context, {"amount": 600}))

    assert result == {
        "amount": "R$ 600,00",
        "interest_free": True,
        "max_installments": 6,
        "options": [
            {"installments": 1, "installment_amount": "R$ 600,00"},
            {"installments": 2, "installment_amount": "R$ 300,00"},
            {"installments": 3, "installment_amount": "R$ 200,00"},
            {"installments": 4, "installment_amount": "R$ 150,00"},
            {"installments": 5, "installment_amount": "R$ 120,00"},
            {"installments": 6, "installment_amount": "R$ 100,00"},
        ],
        "requested_installments": None,
        "requested_allowed": None,
        "policy_section": "3.1",
    }


@pytest.mark.parametrize(
    ("arguments", "allowed"),
    [
        ({"amount": 600, "installments": 6}, True),
        ({"amount": "600", "installments": "1"}, True),
        ({"amount": 600, "installments": 10}, False),
        ({"amount": 120, "installments": 3}, False),
        ({"amount": 1200, "installments": 12}, True),
        ({"amount": 1200, "installments": 18}, False),
    ],
)
def test_quote_installments_answers_the_requested_count(arguments, allowed, context):
    result = json.loads(quote_installments(context, arguments))

    assert result["requested_installments"] == int(arguments["installments"])
    assert result["requested_allowed"] is allowed


def test_quote_installments_for_120_never_offers_three_payments(context):
    result = json.loads(quote_installments(context, {"amount": "120.00"}))

    assert result["max_installments"] == 2
    assert [option["installment_amount"] for option in result["options"]] == [
        "R$ 120,00",
        "R$ 60,00",
    ]


def test_quote_installments_rounds_amount_to_cents(context):
    result = json.loads(quote_installments(context, {"amount": "1000.004"}))

    assert result["amount"] == "R$ 1.000,00"
    assert result["max_installments"] == 10
    assert result["options"][2]["installment_amount"] == "R$ 333,33"


@pytest.mark.parametrize(
    ("arguments", "field"),
    [
        ({}, "amount"),
        ({"amount": 0}, "amount"),
        ({"amount": -10}, "amount"),
        ({"amount": "NaN"}, "amount"),
        ({"amount": "seiscentos"}, "amount"),
        ({"amount": True}, "amount"),
        ({"amount": 600, "installments": 0}, "installments"),
        ({"amount": 600, "installments": True}, "installments"),
        ({"amount": 600, "juros": True}, "juros"),
    ],
)
def test_quote_installments_rejects_invalid_arguments(arguments, field, context, reporter):
    result = json.loads(quote_installments(context, arguments))

    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == field
    [(scope, _)] = reporter.reports
    assert scope == "tools.quote_installments"
