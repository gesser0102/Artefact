from decimal import Decimal

from emporio_agent.agent.tools.serialization import (
    serialize_product_lookup,
    serialize_promotions,
    serialize_search_result,
    serialize_summary,
    to_tool_json,
)
from emporio_agent.application.catalog.dtos import (
    ActivePromotion,
    AmbiguousProduct,
    ProductDetails,
    ProductSummary,
    SearchResult,
)
from emporio_agent.domain.availability import Availability
from emporio_agent.domain.pricing import quote_price


def summary(discount_percent=None, availability=Availability.AVAILABLE) -> ProductSummary:
    return ProductSummary(
        product_id=1,
        name="Violão",
        category="Violões",
        quote=quote_price(Decimal("359"), discount_percent),
        availability=availability,
        stock_quantity=3,
    )


def test_to_tool_json_is_compact_and_keeps_accents():
    assert to_tool_json({"nome": "Violão", "preço": 1}) == '{"nome":"Violão","preço":1}'


def test_summary_preserves_field_order_and_formats_money():
    assert list(serialize_summary(summary()).items()) == [
        ("product_id", 1),
        ("name", "Violão"),
        ("category", "Violões"),
        ("price", "R$ 359,00"),
        ("availability", "available"),
        ("promotion", None),
        ("stock_quantity", 3),
    ]


def test_summary_reports_promotion_from_quote():
    serialized = serialize_summary(summary(discount_percent=10))

    assert serialized["price"] == "R$ 323,10"
    assert serialized["promotion"] == {"original_price": "R$ 359,00", "discount_percent": 10}


def test_search_result_derives_returned_from_items():
    assert (
        serialize_search_result(SearchResult(total_matches=9, items=(summary(),)))["returned"] == 1
    )


def test_lookup_not_found():
    assert serialize_product_lookup(None) == {"found": False}


def test_lookup_ambiguous():
    serialized = serialize_product_lookup(AmbiguousProduct(total_matches=2, matches=(summary(),)))

    assert serialized["found"] is True
    assert serialized["ambiguous"] is True
    assert serialized["total_matches"] == 2
    assert len(serialized["matches"]) == 1


def test_lookup_omits_unreliable_details_and_absent_alternatives():
    serialized = serialize_product_lookup(
        ProductDetails(
            summary=summary(),
            details_reliable=False,
            description=None,
            specs=None,
            alternatives=None,
        )
    )

    assert serialized["details_reliable"] is False
    assert not {"description", "specs", "alternatives"} & serialized.keys()


def test_lookup_keeps_empty_alternatives_for_unavailable_product():
    serialized = serialize_product_lookup(
        ProductDetails(
            summary=summary(availability=Availability.DISCONTINUED),
            details_reliable=True,
            description="Descrição",
            specs={"top": "Spruce"},
            alternatives=(),
        )
    )

    assert serialized["alternatives"] == []
    assert serialized["specs"] == {"top": "Spruce"}


def test_promotions_report_total():
    promotion = ActivePromotion(
        promotion_id=7,
        product_id=1,
        name="Violão",
        description="Promoção",
        quote=quote_price(Decimal("359"), 10),
        availability=Availability.AVAILABLE,
    )

    assert serialize_promotions([promotion]) == {
        "total": 1,
        "promotions": [
            {
                "promotion_id": 7,
                "product_id": 1,
                "name": "Violão",
                "description": "Promoção",
                "original_price": "R$ 359,00",
                "discount_percent": 10,
                "final_price": "R$ 323,10",
                "availability": "available",
            }
        ],
    }
