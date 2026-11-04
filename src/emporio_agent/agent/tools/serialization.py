import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
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
from emporio_agent.application.orders.dtos import (
    NotVerified,
    OrderLookup,
    ReturnLookup,
)
from emporio_agent.application.policies.dtos import (
    PolicyExcerpt,
    PolicyIndexEntry,
    PolicyLookup,
    PolicySearchResult,
)
from emporio_agent.domain.models import OrderStatus
from emporio_agent.domain.pricing import InstallmentOption, PriceQuote, format_brl

INSTALLMENT_POLICY_SECTION = "3.1"
INVALID_ARGUMENTS_ERROR = "invalid_arguments"
UNKNOWN_TOOL_ERROR = "unknown_tool"
TOOL_FAILED_ERROR = "tool_failed"
ARGUMENTS_FIELD = "arguments"
RECEIVED_ON_FIELD = "received_on"
INVALID_RECEIVED_ON_MESSAGE = (
    "A data de recebimento não pode ser futura nem anterior à data do pedido."
)
ORDER_STATUS_LABELS = {
    OrderStatus.PENDING: "Pendente",
    OrderStatus.CONFIRMED: "Confirmado",
    OrderStatus.SHIPPED: "Enviado",
    OrderStatus.DELIVERED: "Entregue",
    OrderStatus.CANCELLED: "Cancelado",
}
PAYMENT_METHOD_LABELS = {
    "pix": "PIX",
    "debit": "Cartão de débito",
    "boleto": "Boleto bancário",
}
CREDIT_PAYMENT_PATTERN = re.compile(r"credit_([0-9]+)x")
CREDIT_PAYMENT_LABEL = "Cartão de crédito em {installments}x"
UNKNOWN_PAYMENT_METHOD_LABEL = "Forma de pagamento não identificada"
UNRELIABLE_DETAILS_NOTE = (
    "No confirmed description or specs for this product; tell the customer the information is "
    "not confirmed and do not state specs from memory."
)


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


def serialize_installment_quote(
    amount: Decimal,
    options: Sequence[InstallmentOption],
    requested: int | None,
) -> dict[str, Any]:
    max_count = options[-1].installments
    return {
        "amount": format_brl(amount),
        "interest_free": True,
        "max_installments": max_count,
        "options": [
            {
                "installments": option.installments,
                "installment_amount": format_brl(option.installment_amount),
            }
            for option in options
        ],
        "requested_installments": requested,
        "requested_allowed": None if requested is None else requested <= max_count,
        "policy_section": INSTALLMENT_POLICY_SECTION,
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
    else:
        details["details_note"] = UNRELIABLE_DETAILS_NOTE
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


def serialize_policy_excerpt(excerpt: PolicyExcerpt) -> dict[str, Any]:
    return {
        "section_id": excerpt.section_id,
        "title": excerpt.title,
        "parent_title": excerpt.parent_title,
        "clarifications": list(excerpt.clarifications),
        "text": excerpt.text,
    }


def serialize_available_sections(entries: Iterable[PolicyIndexEntry]) -> list[dict[str, Any]]:
    return [{"section_id": entry.section_id, "title": entry.title} for entry in entries]


def serialize_policy_search(
    result: PolicySearchResult,
    available_sections: Iterable[PolicyIndexEntry],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "query_matched": bool(result.sections),
        "sections": [serialize_policy_excerpt(excerpt) for excerpt in result.sections],
    }
    if not result.sections:
        serialized["available_sections"] = serialize_available_sections(available_sections)
    return serialized


def serialize_policy_lookup(
    lookup: PolicyLookup,
    available_sections: Iterable[PolicyIndexEntry],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "sections": [serialize_policy_excerpt(excerpt) for excerpt in lookup.sections],
        "unknown_section_ids": list(lookup.unknown_section_ids),
    }
    if not lookup.sections:
        serialized["available_sections"] = serialize_available_sections(available_sections)
    return serialized


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


def serialize_invalid_received_on() -> dict[str, Any]:
    return {
        "error": INVALID_ARGUMENTS_ERROR,
        "details": [{"field": RECEIVED_ON_FIELD, "message": INVALID_RECEIVED_ON_MESSAGE}],
    }


def serialize_not_verified() -> dict[str, Any]:
    return {"verified": False}


def serialize_locked() -> dict[str, Any]:
    return {"verified": False, "locked": True}


def serialize_error(code: str) -> dict[str, Any]:
    return {"error": code}


def parse_tool_arguments(arguments_json: str) -> dict[str, Any]:
    if not arguments_json.strip():
        return {}
    parsed = json.loads(arguments_json)
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def error_code_of(output: str) -> str | None:
    try:
        parsed = json.loads(output)
    except ValueError:
        return None
    code = parsed.get("error") if isinstance(parsed, dict) else None
    return code if isinstance(code, str) else None


def iso_date_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def payment_method_label(payment_method: str) -> str:
    credit_payment = CREDIT_PAYMENT_PATTERN.fullmatch(payment_method)
    if credit_payment is not None:
        return CREDIT_PAYMENT_LABEL.format(installments=credit_payment.group(1))
    return PAYMENT_METHOD_LABELS.get(payment_method, UNKNOWN_PAYMENT_METHOD_LABEL)


def serialize_order_lookup(lookup: OrderLookup) -> dict[str, Any]:
    if isinstance(lookup, NotVerified):
        return serialize_not_verified()
    serialized: dict[str, Any] = {
        "verified": True,
        "order_id": lookup.order_id,
        "customer_first_name": lookup.customer_first_name,
        "status": lookup.status.value,
        "status_label": ORDER_STATUS_LABELS[lookup.status],
        "order_date": lookup.order_date.isoformat(),
        "order_value": format_brl(lookup.order_value),
        "payment_method_label": payment_method_label(lookup.payment_method),
        "tracking_code": lookup.tracking_code,
        "estimated_delivery": iso_date_or_none(lookup.estimated_delivery),
        "items": [{"name": item.name, "quantity": item.quantity} for item in lookup.items],
        "requires_human_followup": lookup.requires_human_followup,
        "followup_reason": None if lookup.followup_reason is None else lookup.followup_reason.value,
    }
    if lookup.status is OrderStatus.CANCELLED:
        serialized["cancellation_note"] = lookup.cancellation_note
    return serialized


def serialize_return_lookup(lookup: ReturnLookup) -> dict[str, Any]:
    if isinstance(lookup, NotVerified):
        return serialize_not_verified()
    assessment = lookup.assessment
    return {
        "verified": True,
        "order_id": lookup.order_id,
        "outcome": assessment.outcome.value,
        "missing_information": [item.value for item in assessment.missing_information],
        "deadline": iso_date_or_none(assessment.deadline),
        "policy_section": assessment.policy_section,
        "next_step": assessment.next_step.value,
        "requirements": [item.value for item in assessment.requirements],
        "legal_warranty_note": assessment.legal_warranty_note,
    }
