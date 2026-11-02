from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from emporio_agent.agent.tools.schemas import (
    GetProductInput,
    ListActivePromotionsInput,
    ListCategoriesInput,
    SearchProductsInput,
    ToolInput,
)
from emporio_agent.agent.tools.serialization import (
    serialize_categories,
    serialize_invalid_arguments,
    serialize_product_lookup,
    serialize_promotions,
    serialize_search_result,
    to_tool_json,
)
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.ports import ErrorReporter

type ToolArguments = Mapping[str, object] | None


@dataclass(frozen=True)
class ToolContext:
    catalog: CatalogService
    report_error: ErrorReporter


def run_tool[Input: ToolInput](
    context: ToolContext,
    tool_name: str,
    input_model: type[Input],
    arguments: ToolArguments,
    execute: Callable[[Input], Mapping[str, Any]],
) -> str:
    try:
        parsed_arguments = input_model.model_validate({} if arguments is None else arguments)
    except ValidationError as error:
        context.report_error(f"tools.{tool_name}", error)
        return to_tool_json(serialize_invalid_arguments(error))
    return to_tool_json(execute(parsed_arguments))


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
