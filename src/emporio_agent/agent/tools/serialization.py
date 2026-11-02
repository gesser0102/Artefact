import json
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from emporio_agent.application.catalog.dtos import (
    ActivePromotion,
    AmbiguousProduct,
    CategoryOverview,
    ProductLookup,
    ProductSummary,
    SearchResult,
)
from emporio_agent.domain.pricing import PriceQuote, format_brl

INVALID_ARGUMENTS_ERROR = "invalid_arguments"
ARGUMENTS_FIELD = "arguments"


def to_tool_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def serialize_quote(quote: PriceQuote) -> dict[str, Any]:
    return {
        "list_price": format_brl(quote.list_price),
        "discount_percent": quote.discount_percent,
        "final_price": format_brl(quote.final_price),
        "pix_price": None if quote.pix_price is None else format_brl(quote.pix_price),
        "max_installments": quote.max_installments,
        "installment_amount": format_brl(quote.installment_amount),
    }


def serialize_summary(summary: ProductSummary) -> dict[str, Any]:
    quote = summary.quote
    promotion = (
        None
        if quote.discount_percent is None
        else {
            "original_price": format_brl(quote.list_price),
            "discount_percent": quote.discount_percent,
        }
    )
    return {
        "product_id": summary.product_id,
        "name": summary.name,
        "category": summary.category,
        "price": format_brl(quote.final_price),
        "availability": summary.availability.value,
        "promotion": promotion,
        "stock_quantity": summary.stock_quantity,
    }


def serialize_search_result(result: SearchResult) -> dict[str, Any]:
    return {
        "total_matches": result.total_matches,
        "returned": len(result.items),
        "items": [serialize_summary(item) for item in result.items],
    }


def serialize_product_lookup(lookup: ProductLookup) -> dict[str, Any]:
    if lookup is None:
        return {"found": False}
    if isinstance(lookup, AmbiguousProduct):
        return {
            "found": True,
            "ambiguous": True,
            "total_matches": lookup.total_matches,
            "matches": [serialize_summary(item) for item in lookup.matches],
        }
    details: dict[str, Any] = {
        "found": True,
        **serialize_summary(lookup.summary),
        "quote": serialize_quote(lookup.summary.quote),
        "details_reliable": lookup.details_reliable,
    }
    if lookup.details_reliable:
        details["description"] = lookup.description
        details["specs"] = lookup.specs
    if lookup.alternatives is not None:
        details["alternatives"] = [serialize_summary(item) for item in lookup.alternatives]
    return details


def serialize_categories(categories: Iterable[CategoryOverview]) -> dict[str, Any]:
    return {
        "categories": [
            {
                "category_id": category.category_id,
                "name": category.name,
                "available_products": category.available_products,
            }
            for category in categories
        ]
    }


def serialize_promotions(promotions: Iterable[ActivePromotion]) -> dict[str, Any]:
    serialized = [
        {
            "promotion_id": promotion.promotion_id,
            "product_id": promotion.product_id,
            "name": promotion.name,
            "description": promotion.description,
            "original_price": format_brl(promotion.quote.list_price),
            "discount_percent": promotion.quote.discount_percent,
            "final_price": format_brl(promotion.quote.final_price),
            "availability": promotion.availability.value,
        }
        for promotion in promotions
    ]
    return {"total": len(serialized), "promotions": serialized}


def serialize_invalid_arguments(error: ValidationError) -> dict[str, Any]:
    return {
        "error": INVALID_ARGUMENTS_ERROR,
        "details": [
            {
                "field": str(issue["loc"][0]) if issue["loc"] else ARGUMENTS_FIELD,
                "message": issue["msg"],
            }
            for issue in error.errors(include_url=False, include_context=False, include_input=False)
        ],
    }
