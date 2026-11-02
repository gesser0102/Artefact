import json
from decimal import Decimal

import pytest

from emporio_agent.agent.tools.catalog_tools import (
    get_product,
    list_active_promotions,
    list_categories,
    search_products,
)
from emporio_agent.agent.tools.schemas import MAX_SEARCH_LIMIT
from emporio_agent.agent.tools.serialization import serialize_search_result, to_tool_json
from emporio_agent.application.catalog.query_parser import CATEGORY_IDS_BY_TOKEN
from emporio_agent.application.catalog.service import UNRELIABLE_DETAIL_PRODUCT_IDS

VIOLOES_UP_TO_1000 = [83, 85, 89, 88, 81, 84, 87, 86, 107, 82, 91, 112]
LARGE_LIMIT = 200


def search(tools, **arguments) -> dict:
    return json.loads(search_products(tools, arguments))


def lookup(tools, **arguments) -> dict:
    return json.loads(get_product(tools, arguments))


def categories(tools) -> dict:
    return json.loads(list_categories(tools))


def promotions(tools) -> dict:
    return json.loads(list_active_promotions(tools))


def full_search(service, **arguments) -> dict:
    result = service.search_products(**arguments, limit=LARGE_LIMIT)
    return json.loads(to_tool_json(serialize_search_result(result)))


def ids_of(result: dict) -> list[int]:
    return [item["product_id"] for item in result["items"]]


def category_ids_of(repository, result: dict) -> set[int]:
    return {repository.products_by_id[item["product_id"]].category_id for item in result["items"]}


def test_criterion_1_violoes_up_to_1000_with_full_limit(service):
    result = full_search(service, category="violões", max_price=Decimal(1000))

    assert ids_of(result) == VIOLOES_UP_TO_1000
    assert result["total_matches"] == 12
    assert result["returned"] == 12


def test_criterion_1_default_limit_truncates_but_reports_total(tools):
    result = search(tools, category="violões", max_price=1000)

    assert ids_of(result) == VIOLOES_UP_TO_1000[:8]
    assert result["total_matches"] == 12
    assert result["returned"] == 8


@pytest.mark.parametrize("category", [5, "5", "Violões", "violoes", "violão"])
def test_category_argument_accepts_id_name_and_variants(tools, category):
    result = search(tools, category=category, max_price=1000)

    assert result["total_matches"] == 12


def test_category_argument_accepts_full_category_names(repository, service):
    for category in repository.categories_by_id.values():
        result = full_search(service, category=category.name)
        assert category_ids_of(repository, result) <= {category.category_id}


def test_unknown_category_argument_filters_everything_out(tools):
    assert search(tools, category="acessórios")["total_matches"] == 0


def test_criterion_2_takamine_gd20(tools):
    search_result = search(tools, query="Takamine GD20")
    item = search_result["items"][0]
    details = lookup(tools, name="Takamine GD20")

    assert ids_of(search_result) == [95]
    assert item["price"] == "R$ 2.199,00"
    assert item["availability"] == "available"
    assert item["promotion"] is None
    assert details["product_id"] == 95
    assert details["promotion"] is None
    assert details["quote"] == {
        "list_price": "R$ 2.199,00",
        "discount_percent": None,
        "final_price": "R$ 2.199,00",
        "pix_price": "R$ 2.089,05",
        "max_installments": 12,
        "installment_amount": "R$ 183,25",
    }


@pytest.mark.parametrize("query", ["gd-20", "GD20", "gd 20", "Gd.20", "takamine gd-20"])
def test_model_code_variants_find_product_95(tools, query):
    assert ids_of(search(tools, query=query)) == [95]


def test_accents_and_case_are_normalized_in_text_search(service):
    accented = full_search(service, query="ELÉTRICO")
    plain = full_search(service, query="eletrico")

    assert ids_of(accented) == ids_of(plain)
    assert accented["total_matches"] > 0


def test_criterion_3_out_of_stock_has_alternatives(tools):
    details = lookup(tools, product_id=96)

    assert details["availability"] == "out_of_stock"
    assert [item["product_id"] for item in details["alternatives"]] == [107, 82, 86]
    assert all(item["availability"] == "available" for item in details["alternatives"])


@pytest.mark.parametrize("product_id", [113, 136])
def test_criterion_3_discontinued_products(repository, tools, product_id):
    details = lookup(tools, product_id=product_id)
    category_id = repository.products_by_id[product_id].category_id

    assert details["availability"] == "discontinued"
    assert 0 < len(details["alternatives"]) <= 3
    for alternative in details["alternatives"]:
        assert alternative["availability"] == "available"
        assert repository.products_by_id[alternative["product_id"]].category_id == category_id


def test_criterion_3_coming_soon_is_hidden_by_default_despite_stock(tools, service):
    details = lookup(tools, product_id=130)
    default_search = full_search(service, category="ukulele")
    with_unavailable = full_search(service, category="ukulele", include_unavailable=True)

    assert details["availability"] == "coming_soon"
    assert details["stock_quantity"] == 2
    assert "alternatives" in details
    assert 130 not in ids_of(default_search)
    assert 130 in ids_of(with_unavailable)


def test_available_product_has_no_alternatives(tools):
    assert "alternatives" not in lookup(tools, product_id=95)


def test_alternatives_exclude_products_of_other_categories_when_few_remain(tools):
    alternatives = lookup(tools, product_id=136)["alternatives"]

    assert [item["product_id"] for item in alternatives] == [138, 135, 137]


def test_criterion_4_promotional_product_127(tools):
    details = lookup(tools, product_id=127)

    assert details["quote"]["list_price"] == "R$ 359,00"
    assert details["quote"]["discount_percent"] == 10
    assert details["quote"]["final_price"] == "R$ 323,10"
    assert details["quote"]["pix_price"] is None
    assert details["price"] == "R$ 323,10"
    assert details["promotion"] == {"original_price": "R$ 359,00", "discount_percent": 10}


def test_criterion_4_exactly_four_active_promotions(tools):
    result = promotions(tools)

    assert [promotion["product_id"] for promotion in result["promotions"]] == [127, 121, 90, 94]
    assert result["total"] == 4
    assert result["promotions"][0]["original_price"] == "R$ 359,00"
    assert result["promotions"][0]["discount_percent"] == 10
    assert result["promotions"][0]["final_price"] == "R$ 323,10"


def test_criterion_5_installments_through_product_quote(tools):
    assert lookup(tools, product_id=81)["quote"]["max_installments"] == 6
    assert lookup(tools, product_id=92)["quote"]["max_installments"] == 12


def test_price_filters_use_final_price_with_promotion(tools):
    below_promotional_price = search(tools, category="ukulele", min_price=323, max_price=324)
    list_price_only = search(tools, category="ukulele", min_price=350, max_price=359)

    assert ids_of(below_promotional_price) == [127]
    assert 127 not in ids_of(list_price_only)


def test_price_filters_do_not_use_pix_price(tools):
    assert 95 not in ids_of(search(tools, category="violões", max_price=2100))


def test_results_are_sorted_by_final_price_across_promotions(repository, service):
    result = full_search(service, category="ukulele")
    prices = [
        repository.products_by_id[item["product_id"]].price_brl
        * (Decimal("0.9") if item["product_id"] == 127 else 1)
        * (Decimal("0.8") if item["product_id"] == 121 else 1)
        for item in result["items"]
    ]

    assert prices == sorted(prices)


@pytest.mark.parametrize("bound", ["abc", "NaN", "Infinity"])
def test_invalid_price_bound_returns_invalid_arguments(tools, bound):
    result = search(tools, max_price=bound)

    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == "max_price"


def test_float_bound_is_compared_as_decimal(tools):
    assert ids_of(search(tools, category="ukulele", min_price=323.1, max_price=323.1)) == [127]


def test_limit_zero_returns_only_counts(tools):
    result = search(tools, category="violões", limit=0)

    assert result["items"] == []
    assert result["total_matches"] > 0


def test_criterion_6_unreliable_description_is_not_searched(tools):
    assert 135 not in ids_of(search(tools, query="Fender Jazz Bass", include_unavailable=True))
    assert search(tools, query="Pearl Export")["total_matches"] == 0
    assert ids_of(search(tools, query="Pearl")) == [140]


def test_criterion_6_unreliable_product_omits_details(tools):
    details = lookup(tools, product_id=135)

    assert "description" not in details
    assert "specs" not in details
    assert details["details_reliable"] is False


@pytest.mark.parametrize("product_id", sorted(UNRELIABLE_DETAIL_PRODUCT_IDS))
def test_every_unreliable_product_omits_details(tools, product_id):
    details = lookup(tools, product_id=product_id)

    assert details["found"] is True
    assert "description" not in details
    assert "specs" not in details
    assert details["details_reliable"] is False


def test_reliable_product_exposes_details(tools):
    details = lookup(tools, product_id=145)

    assert details["details_reliable"] is True
    assert details["description"]
    assert details["specs"]["strings"] == "6"


def test_criterion_7_violao_never_returns_ukulele_128(repository, service):
    result = full_search(service, query="violão", include_unavailable=True)

    assert 128 not in ids_of(result)
    assert category_ids_of(repository, result) == {5}


@pytest.mark.parametrize(
    ("query", "category_id"),
    [
        ("guitarra", 1),
        ("guitarras", 1),
        ("Guitarra", 1),
        ("baixo", 2),
        ("baixos", 2),
        ("bateria", 3),
        ("baterias", 3),
        ("percussão", 3),
        ("percussao", 3),
        ("teclado", 4),
        ("teclados", 4),
        ("piano", 4),
        ("pianos", 4),
        ("violão", 5),
        ("violao", 5),
        ("violões", 5),
        ("violoes", 5),
        ("VIOLÃO", 5),
        ("ukulele", 9),
        ("ukuleles", 9),
        ("ukulelê", 9),
    ],
)
def test_criterion_7_category_tokens_return_only_their_category(
    repository, service, query, category_id
):
    result = full_search(service, query=query, include_unavailable=True)

    assert result["total_matches"] > 0
    assert category_ids_of(repository, result) == {category_id}


def test_every_category_has_a_token(repository):
    tokens_ids = frozenset().union(*CATEGORY_IDS_BY_TOKEN.values())

    assert tokens_ids == frozenset(repository.categories_by_id)


@pytest.mark.parametrize("query", ["sopro", "sopros", "orquestral", "cordas orquestrais"])
def test_categories_without_stock_return_empty(tools, query):
    assert search(tools, query=query, include_unavailable=True)["total_matches"] == 0


@pytest.mark.parametrize(
    "query",
    ["cordas", "corda", "Cordas!", "as cordas", "cordas de nylon", "cordas de aço"],
)
def test_strings_without_category_or_count_match_nothing(service, query):
    result = full_search(service, query=query, include_unavailable=True)

    assert result == {"total_matches": 0, "returned": 0, "items": []}


def test_strings_with_context_still_search_as_text(service):
    seven_strings = full_search(service, query="7 cordas")
    within_category = full_search(service, query="cordas", category=5)

    assert ids_of(seven_strings) == [112, 110, 109, 111]
    assert 83 in ids_of(within_category)


def test_category_token_combines_with_text(tools, service):
    assert ids_of(search(tools, query="baixo yamaha")) == [137]
    assert ids_of(full_search(service, query="violão para iniciantes"))


def test_singular_query_matches_plural_text_by_prefix(service):
    singular = full_search(service, query="violão iniciante")
    plural = full_search(service, query="violão iniciantes")

    assert singular["total_matches"] == plural["total_matches"] > 0


def test_numbers_do_not_match_by_prefix(tools):
    assert search(tools, query="Martin 2")["total_matches"] == 0


def test_criterion_8_electronics_uses_specs(service):
    with_electronics = full_search(service, category="violões", electronics=True)
    without_electronics = full_search(service, category="violões", electronics=False)

    assert 94 in ids_of(with_electronics)
    assert 94 not in ids_of(without_electronics)
    assert 81 in ids_of(without_electronics)


def test_electronics_filter_requires_explicit_spec(service):
    assert 145 not in ids_of(full_search(service, electronics=True))
    assert 145 not in ids_of(full_search(service, electronics=False))


def test_criterion_9_list_categories_keeps_empty_categories(repository, tools):
    counts = {
        category["category_id"]: category["available_products"]
        for category in categories(tools)["categories"]
    }

    assert counts[6] == 0
    assert counts[7] == 0
    assert counts[8] == 0
    assert counts[1] == 5
    assert set(counts) == set(repository.categories_by_id)


def test_get_product_by_ambiguous_name_returns_matches(tools):
    result = lookup(tools, name="Martin D-28")

    assert result["ambiguous"] is True
    assert [item["product_id"] for item in result["matches"]] == [93, 108]
    assert result["total_matches"] == 2


def test_get_product_by_broad_name_caps_matches(tools):
    result = lookup(tools, name="Yamaha")

    assert result["ambiguous"] is True
    assert result["total_matches"] > len(result["matches"]) == 8


def test_get_product_by_exact_name_is_not_ambiguous(tools):
    assert lookup(tools, name="yamaha c40 nylon natural")["product_id"] == 81


def test_get_product_finds_unavailable_product_by_name(tools):
    assert lookup(tools, name="Shelby SN-7C")["availability"] == "discontinued"


@pytest.mark.parametrize(
    "arguments",
    [{"product_id": 9999}, {"name": "Stradivarius"}, {"name": ""}, {"name": "de"}, {}],
)
def test_get_product_not_found(tools, arguments):
    assert lookup(tools, **arguments) == {"found": False}


def test_criterion_10_every_tool_output_is_json_serializable(repository, tools, service):
    full_catalog = service.search_products(include_unavailable=True, limit=LARGE_LIMIT)
    outputs = [
        to_tool_json(serialize_search_result(full_catalog)),
        search_products(tools, {"include_unavailable": True, "limit": MAX_SEARCH_LIMIT}),
        list_categories(tools),
        list_active_promotions(tools),
        get_product(tools, {"name": "Yamaha"}),
        get_product(tools, {"product_id": 9999}),
        *(
            get_product(tools, {"product_id": product_id})
            for product_id in repository.products_by_id
        ),
    ]

    for output in outputs:
        assert isinstance(output, str)
        assert isinstance(json.loads(output), dict)


def test_get_product_specs_are_a_copy(repository, service):
    service.get_product(product_id=81).specs["top"] = "changed"

    assert repository.products_by_id[81].specs["top"] == "Spruce"


@pytest.mark.parametrize(
    "arguments",
    [
        {"category": "violões", "max_price": 1000},
        {"query": "violão"},
        {"category": "ukulele"},
        {"query": "yamaha"},
        {"query": "elétrico"},
    ],
)
def test_criterion_11_typical_search_payload_stays_compact(tools, arguments):
    payload = search_products(tools, arguments)
    result = json.loads(payload)

    assert result["returned"] == 8
    assert len(payload) < 1500


def test_criterion_11_all_output_money_is_formatted(tools):
    result = search(tools, query="ukulele")

    assert all(item["price"].startswith("R$ ") for item in result["items"])


def test_search_tool_returns_the_same_items_as_the_service(tools, service):
    tool_result = search(tools, include_unavailable=True, limit=MAX_SEARCH_LIMIT)
    service_result = full_search(service, include_unavailable=True)

    assert tool_result["items"] == service_result["items"][:MAX_SEARCH_LIMIT]
    assert tool_result["total_matches"] == service_result["total_matches"]
