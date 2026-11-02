import json

import pytest

from emporio_agent.agent.tools.catalog_tools import get_product, search_products

GUITARRAS_CATEGORY_ID = 1
BAIXOS_CATEGORY_ID = 2
VIOLOES_CATEGORY_ID = 5
UKULELES_CATEGORY_ID = 9


def search(tools, **arguments) -> dict:
    return json.loads(search_products(tools, arguments))


def lookup(tools, **arguments) -> dict:
    return json.loads(get_product(tools, arguments))


def category_ids_of(repository, result: dict) -> set[int]:
    return {repository.products_by_id[item["product_id"]].category_id for item in result["items"]}


@pytest.mark.parametrize("query", ["contrabaixo", "contrabaixos", "Contrabaixo elétrico"])
def test_contrabaixo_finds_baixos_category(repository, tools, query):
    result = search(tools, query=query)

    assert result["total_matches"] > 0
    assert category_ids_of(repository, result) == {BAIXOS_CATEGORY_ID}


def test_guitarra_eletrica_finds_guitarras(repository, tools):
    result = search(tools, query="guitarra elétrica")

    assert result["total_matches"] == 5
    assert category_ids_of(repository, result) == {GUITARRAS_CATEGORY_ID}


@pytest.mark.parametrize("query", ["uquelele", "ukelele", "uqueleles"])
def test_ukulele_spelling_variants_find_ukuleles(repository, tools, query):
    result = search(tools, query=query)

    assert result["total_matches"] == 14
    assert category_ids_of(repository, result) == {UKULELES_CATEGORY_ID}


@pytest.mark.parametrize(
    "query",
    ["guitarra barata", "guitarra de preço baixo", "guitarra mais barata", "guitarra boa"],
)
def test_price_words_do_not_empty_a_category_search(repository, tools, query):
    result = search(tools, query=query)

    assert result["total_matches"] == 5
    assert category_ids_of(repository, result) == {GUITARRAS_CATEGORY_ID}


def test_price_adjective_does_not_add_baixos_category(repository, tools):
    result = search(tools, query="violão de preço baixo")

    assert category_ids_of(repository, result) == {VIOLOES_CATEGORY_ID}


def test_baixo_keeps_instrument_meaning_with_price_word_alone(repository, tools):
    result = search(tools, query="preço do baixo")

    assert category_ids_of(repository, result) == {BAIXOS_CATEGORY_ID}


@pytest.mark.parametrize(
    "query",
    ["amplificador", "amplificadores", "palheta", "cabo", "capa", "case", "pedal", "pedais"],
)
def test_accessory_terms_return_no_instruments(tools, query):
    assert search(tools, query=query)["total_matches"] == 0


@pytest.mark.parametrize("product_id", ["95", " 95 ", 95])
def test_get_product_accepts_id_as_text_or_integer(tools, product_id):
    result = lookup(tools, product_id=product_id)

    assert result["found"] is True
    assert result["product_id"] == 95


@pytest.mark.parametrize("product_id", ["-95", 9999])
def test_get_product_rejects_unknown_ids(tools, product_id):
    assert lookup(tools, product_id=product_id) == {"found": False}


def test_get_product_rejects_non_numeric_id_as_invalid_arguments(tools):
    result = lookup(tools, product_id="abc")

    assert result["error"] == "invalid_arguments"
    assert result["details"][0]["field"] == "product_id"
