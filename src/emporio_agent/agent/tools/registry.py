from collections.abc import Callable, Mapping
from typing import Any

from emporio_agent.agent.tools.catalog_tools import (
    QUOTE_INSTALLMENTS,
    get_product,
    list_active_promotions,
    list_categories,
    quote_installments,
    search_products,
)
from emporio_agent.agent.tools.context import ToolArguments, ToolContext
from emporio_agent.agent.tools.order_tools import (
    ASSESS_RETURN_ELIGIBILITY,
    GET_ORDER_STATUS,
    assess_return_eligibility,
    get_order_status,
)
from emporio_agent.agent.tools.policy_tools import (
    GET_POLICY_SECTIONS,
    SEARCH_POLICIES,
    get_policy_sections,
    search_policies,
)
from emporio_agent.agent.tools.schemas import (
    MAX_INSTALLMENT_QUOTE_AMOUNT,
    MAX_POLICY_SECTION_IDS,
    MAX_REQUESTED_INSTALLMENTS,
    MAX_SEARCH_LIMIT,
)
from emporio_agent.application.conversation.messages import ToolSpec
from emporio_agent.application.policies.service import MAX_POLICY_SEARCH_LIMIT
from emporio_agent.domain.returns import PurchaseChannel, ReturnReason

SEARCH_PRODUCTS = "search_products"
GET_PRODUCT = "get_product"
LIST_CATEGORIES = "list_categories"
LIST_ACTIVE_PROMOTIONS = "list_active_promotions"
ORDER_TOOL_NAMES = frozenset({GET_ORDER_STATUS, ASSESS_RETURN_ELIGIBILITY})
NULL_TYPE = "null"

type ToolHandler = Callable[[ToolContext, ToolArguments], str]


def nullable(property_schema: Mapping[str, Any]) -> dict[str, Any]:
    declared = property_schema["type"]
    types = list(declared) if isinstance(declared, list) else [declared]
    schema = {**property_schema, "type": [*types, NULL_TYPE]}
    if "enum" in schema:
        schema["enum"] = [*schema["enum"], None]
    return schema


def object_schema(
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            name: property_schema if name in required else nullable(property_schema)
            for name, property_schema in properties.items()
        },
    }
    if required:
        schema["required"] = list(required)
    return schema


ORDER_IDENTITY_PROPERTIES: Mapping[str, Any] = {
    "order_id": {"type": "integer", "description": "Order number typed by the customer."},
    "phone": {
        "type": "string",
        "description": (
            "Registered phone exactly as the customer typed it, including the area code (DDD); "
            "never drop or change digits."
        ),
    },
}

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name=SEARCH_PRODUCTS,
        description=(
            "Search the instrument catalog for price, stock and promotion. Use for any product "
            "question. Returns up to `limit` items plus total_matches; hides unavailable items "
            "unless include_unavailable."
        ),
        parameters=object_schema(
            {
                "query": {"type": "string", "description": "Free text, e.g. 'violão yamaha'."},
                "category": {
                    "type": ["integer", "string"],
                    "description": "Category id or name.",
                },
                "min_price": {"type": "number", "description": "Minimum final price in BRL."},
                "max_price": {"type": "number", "description": "Maximum final price in BRL."},
                "electronics": {
                    "type": "boolean",
                    "description": "true: with electronics/pickup; false: acoustic only.",
                },
                "include_unavailable": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
            }
        ),
    ),
    ToolSpec(
        name=GET_PRODUCT,
        description=(
            "Full details of one product by product_id (preferred) or exact name: price quote, "
            "installments, specs and alternatives when unavailable."
        ),
        parameters=object_schema(
            {"product_id": {"type": "integer"}, "name": {"type": "string"}},
        ),
    ),
    ToolSpec(
        name=LIST_CATEGORIES,
        description="List product categories with the number of available products.",
        parameters=object_schema({}),
    ),
    ToolSpec(
        name=LIST_ACTIVE_PROMOTIONS,
        description="List active promotions with original price, discount and final price.",
        parameters=object_schema({}),
    ),
    ToolSpec(
        name=QUOTE_INSTALLMENTS,
        description=(
            "Interest-free credit card installment options for any amount, per policy 3.1. "
            "Use for every installment question instead of calculating."
        ),
        parameters=object_schema(
            {
                "amount": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": MAX_INSTALLMENT_QUOTE_AMOUNT,
                    "description": "Purchase amount in BRL.",
                },
                "installments": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_REQUESTED_INSTALLMENTS,
                    "description": "Installment count the customer asked about, if any.",
                },
            },
            ("amount",),
        ),
    ),
    ToolSpec(
        name=GET_ORDER_STATUS,
        description=(
            "Order status, tracking and delivery estimate. Call only with the order number AND "
            "the registered phone the customer typed in this chat; never invent or reuse them."
        ),
        parameters=object_schema(ORDER_IDENTITY_PROPERTIES, ("order_id", "phone")),
    ),
    ToolSpec(
        name=ASSESS_RETURN_ELIGIBILITY,
        description=(
            "Exchange/return eligibility for an order. Same identity rule as get_order_status. "
            "If outcome is needs_information, ask the customer for missing_information."
        ),
        parameters=object_schema(
            {
                **ORDER_IDENTITY_PROPERTIES,
                "reason": {"type": "string", "enum": [reason.value for reason in ReturnReason]},
                "channel": {
                    "type": "string",
                    "enum": [channel.value for channel in PurchaseChannel],
                    "description": (
                        "online if bought on the website/app/WhatsApp; in_store if bought at the "
                        "physical store. Fill it whenever the customer already said it."
                    ),
                },
                "received_on": {
                    "type": "string",
                    "description": "Date the customer received the product, YYYY-MM-DD.",
                },
            },
            ("order_id", "phone", "reason"),
        ),
    ),
    ToolSpec(
        name=SEARCH_POLICIES,
        description="Free-text search in the store policy manual when the section is unknown.",
        parameters=object_schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_POLICY_SEARCH_LIMIT},
            },
            ("query",),
        ),
    ),
    ToolSpec(
        name=GET_POLICY_SECTIONS,
        description=(
            "Read policy manual sections by number from the policy index (preferred). "
            "A parent section includes its subsections."
        ),
        parameters=object_schema(
            {
                "section_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": MAX_POLICY_SECTION_IDS,
                },
            },
            ("section_ids",),
        ),
    ),
)

TOOL_HANDLERS: Mapping[str, ToolHandler] = {
    SEARCH_PRODUCTS: search_products,
    GET_PRODUCT: get_product,
    LIST_CATEGORIES: list_categories,
    LIST_ACTIVE_PROMOTIONS: list_active_promotions,
    QUOTE_INSTALLMENTS: quote_installments,
    GET_ORDER_STATUS: get_order_status,
    ASSESS_RETURN_ELIGIBILITY: assess_return_eligibility,
    SEARCH_POLICIES: search_policies,
    GET_POLICY_SECTIONS: get_policy_sections,
}
