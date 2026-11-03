from collections.abc import Mapping
from typing import Any

from emporio_agent.agent.tools.context import ToolArguments, ToolContext, run_tool
from emporio_agent.agent.tools.schemas import (
    GetProductInput,
    ListActivePromotionsInput,
    ListCategoriesInput,
    QuoteInstallmentsInput,
    SearchProductsInput,
)
from emporio_agent.agent.tools.serialization import (
    serialize_categories,
    serialize_installment_quote,
    serialize_product_lookup,
    serialize_promotions,
    serialize_search_result,
)
from emporio_agent.domain.pricing import installment_options, round_money

QUOTE_INSTALLMENTS = "quote_installments"


def search_products(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(parsed: SearchProductsInput) -> Mapping[str, Any]:
        return serialize_search_result(
            context.catalog.search_products(
                query=parsed.query,
                category=parsed.category,
                min_price=parsed.min_price,
                max_price=parsed.max_price,
                electronics=parsed.electronics,
                include_unavailable=parsed.include_unavailable,
                limit=parsed.limit,
            )
        )

    return run_tool(context, "search_products", SearchProductsInput, arguments, execute)


def get_product(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(parsed: GetProductInput) -> Mapping[str, Any]:
        return serialize_product_lookup(
            context.catalog.get_product(product_id=parsed.product_id, name=parsed.name)
        )

    return run_tool(context, "get_product", GetProductInput, arguments, execute)


def list_categories(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(_: ListCategoriesInput) -> Mapping[str, Any]:
        return serialize_categories(context.catalog.list_categories())

    return run_tool(context, "list_categories", ListCategoriesInput, arguments, execute)


def list_active_promotions(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(_: ListActivePromotionsInput) -> Mapping[str, Any]:
        return serialize_promotions(context.catalog.list_active_promotions())

    return run_tool(
        context, "list_active_promotions", ListActivePromotionsInput, arguments, execute
    )


def quote_installments(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(parsed: QuoteInstallmentsInput) -> Mapping[str, Any]:
        amount = round_money(parsed.amount)
        return serialize_installment_quote(amount, installment_options(amount), parsed.installments)

    return run_tool(context, QUOTE_INSTALLMENTS, QuoteInstallmentsInput, arguments, execute)
