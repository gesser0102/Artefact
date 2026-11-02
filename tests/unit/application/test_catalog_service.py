from decimal import Decimal
from pathlib import Path

import pytest

from emporio_agent.application.catalog.dtos import AmbiguousProduct, ProductDetails
from emporio_agent.application.catalog.service import (
    DEFAULT_SEARCH_LIMIT,
    UNRELIABLE_DETAIL_PRODUCT_IDS,
    CatalogService,
)
from emporio_agent.domain.availability import Availability
from emporio_agent.domain.models import ProductStatus
from fakes import InMemoryCatalogRepository, make_category, make_product, make_promotion

GUITARRAS = 1
VIOLOES = 5
OUT_OF_STOCK_ID = 12
DISCONTINUED_ID = 13
COMING_SOON_ID = 14
PROMOTED_ID = 15
UNRELIABLE_ID = 135


@pytest.fixture
def repository() -> InMemoryCatalogRepository:
    return InMemoryCatalogRepository(
        categories=[make_category(GUITARRAS, "Guitarras"), make_category(VIOLOES, "Violões")],
        products=[
            make_product(
                10,
                "Violão Yamaha C40",
                VIOLOES,
                "600",
                specs={"electronics": "no", "top": "Spruce"},
            ),
            make_product(
                11,
                "Violão Takamine GD20",
                VIOLOES,
                "2199",
                description="Eletroacústico para palco",
                specs={"electronics": "yes"},
            ),
            make_product(OUT_OF_STOCK_ID, "Violão Martin", VIOLOES, "2000", stock_quantity=0),
            make_product(
                DISCONTINUED_ID,
                "Violão Antigo",
                VIOLOES,
                "1000",
                status=ProductStatus.DISCONTINUED,
            ),
            make_product(
                COMING_SOON_ID,
                "Violão Futuro",
                VIOLOES,
                "1500",
                status=ProductStatus.COMING_SOON,
            ),
            make_product(PROMOTED_ID, "Guitarra Fender", GUITARRAS, "1000"),
            make_product(16, "Guitarra Gibson", GUITARRAS, "850"),
            make_product(
                UNRELIABLE_ID,
                "Guitarra Misteriosa",
                GUITARRAS,
                "3000",
                description="Fender Jazz Bass",
                specs={"strings": "6"},
            ),
        ],
        promotions=[make_promotion(1, PROMOTED_ID, 20)],
    )


@pytest.fixture
def service(repository) -> CatalogService:
    return CatalogService(repository)


def ids_of(result) -> list[int]:
    return [item.product_id for item in result.items]


def test_disk_guard_is_active():
    with pytest.raises(AssertionError, match="touched the disk"):
        Path("catalog.csv").read_text()
    with pytest.raises(AssertionError, match="touched the disk"), open("catalog.csv"):
        pass


def test_unreliable_ids_are_135_to_144():
    assert frozenset(range(135, 145)) == UNRELIABLE_DETAIL_PRODUCT_IDS


def test_default_search_hides_unavailable_and_sorts_by_final_price(service):
    result = service.search_products()

    assert ids_of(result) == [10, PROMOTED_ID, 16, 11, UNRELIABLE_ID]
    assert result.total_matches == 5


def test_include_unavailable_returns_every_product(service):
    assert service.search_products(include_unavailable=True).total_matches == 8


@pytest.mark.parametrize("category", [VIOLOES, "violões", "Violões", "violão"])
def test_category_filter_accepts_id_and_names(service, category):
    assert ids_of(service.search_products(category=category)) == [10, 11]


def test_unknown_category_filters_everything_out(service):
    assert service.search_products(category="acessórios").total_matches == 0


def test_price_filters_use_final_price(service):
    result = service.search_products(min_price=Decimal(800), max_price=Decimal(800))

    assert ids_of(result) == [PROMOTED_ID]


def test_electronics_filter_requires_explicit_spec(service):
    assert ids_of(service.search_products(electronics=True)) == [11]
    assert ids_of(service.search_products(electronics=False)) == [10]


def test_unreliable_description_is_not_searched(service):
    assert service.search_products(query="Jazz", include_unavailable=True).total_matches == 0
    assert ids_of(service.search_products(query="eletroacústico")) == [11]


def test_accessory_without_context_matches_nothing(service):
    assert service.search_products(query="palheta", include_unavailable=True).total_matches == 0


def test_limit_truncates_but_keeps_total(service):
    result = service.search_products(limit=2)

    assert len(result.items) == 2
    assert result.total_matches == 5


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_returns_only_counts(service, limit):
    result = service.search_products(limit=limit)

    assert result.items == ()
    assert result.total_matches == 5


def test_get_product_by_id_returns_typed_details(service):
    details = service.get_product(product_id=10)

    assert isinstance(details, ProductDetails)
    assert details.summary.availability is Availability.AVAILABLE
    assert details.summary.category == "Violões"
    assert details.summary.quote.final_price == Decimal("600.00")
    assert details.details_reliable is True
    assert details.alternatives is None


def test_get_product_details_never_expose_the_stored_specs(repository, service):
    service.get_product(product_id=10).specs["top"] = "changed"

    assert repository.get_product(10).specs["top"] == "Spruce"


def test_get_product_applies_promotion_to_quote(service):
    quote = service.get_product(product_id=PROMOTED_ID).summary.quote

    assert quote.discount_percent == 20
    assert quote.final_price == Decimal("800.00")
    assert quote.pix_price is None


def test_get_product_omits_unreliable_details(service):
    details = service.get_product(product_id=UNRELIABLE_ID)

    assert details.details_reliable is False
    assert details.description is None
    assert details.specs is None


@pytest.mark.parametrize(
    ("product_id", "availability", "expected_alternatives"),
    [
        (OUT_OF_STOCK_ID, Availability.OUT_OF_STOCK, [11, 10]),
        (DISCONTINUED_ID, Availability.DISCONTINUED, [10, 11]),
        (COMING_SOON_ID, Availability.COMING_SOON, [11, 10]),
    ],
)
def test_unavailable_product_lists_closest_available_alternatives(
    service, product_id, availability, expected_alternatives
):
    details = service.get_product(product_id=product_id)

    assert details.summary.availability is availability
    assert [item.product_id for item in details.alternatives] == expected_alternatives


def test_id_takes_precedence_over_name(service):
    assert service.get_product(product_id=9999, name="Violão Yamaha C40") is None


def test_get_product_by_ambiguous_name_is_sorted_and_capped(repository):
    many = [make_product(i, f"Modelo {i}", VIOLOES, str(100 - i)) for i in range(1, 12)]
    service = CatalogService(
        InMemoryCatalogRepository(categories=repository.list_categories(), products=many)
    )

    result = service.get_product(name="Modelo")

    assert isinstance(result, AmbiguousProduct)
    assert result.total_matches == 11
    assert len(result.matches) == DEFAULT_SEARCH_LIMIT
    assert result.matches[0].product_id == 11


@pytest.mark.parametrize("name", [None, "", "de", "Stradivarius"])
def test_get_product_not_found_returns_none(service, name):
    assert service.get_product(name=name) is None


def test_list_categories_counts_only_available_products(service):
    assert [
        (category.name, category.available_products) for category in service.list_categories()
    ] == [("Guitarras", 3), ("Violões", 2)]


def test_list_active_promotions_returns_typed_quotes(service):
    [promotion] = service.list_active_promotions()

    assert promotion.product_id == PROMOTED_ID
    assert promotion.quote.final_price == Decimal("800.00")
    assert promotion.availability is Availability.AVAILABLE
