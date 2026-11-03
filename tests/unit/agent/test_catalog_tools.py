import json
from datetime import date

import pytest
from pydantic import ValidationError

from emporio_agent.agent.tools.catalog_tools import (
    get_product,
    list_active_promotions,
    list_categories,
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

ALL_TOOLS = [search_products, get_product, list_categories, list_active_promotions]


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
