import pytest

from emporio_agent.application.catalog.query_parser import (
    asks_for_accessory,
    category_ids_for,
    contains_all_tokens,
    parse_query,
    token_matches,
    tokenize,
    with_synonyms,
)


def test_tokenize_removes_accents_case_and_punctuation():
    assert tokenize("Violão ELÉTRICO, gd-20!") == ["violao", "eletrico", "gd", "20"]


def test_parse_query_splits_category_from_text_tokens():
    parsed = parse_query("violão para iniciantes")

    assert parsed.category_ids == frozenset({5})
    assert parsed.text_tokens == ("iniciantes",)


@pytest.mark.parametrize("query", [None, "", "de", "o preço"])
def test_parse_query_without_meaningful_tokens_is_empty(query):
    parsed = parse_query(query)

    assert parsed.category_ids == frozenset()
    assert parsed.text_tokens == ()


def test_price_adjective_is_dropped_only_next_to_another_category():
    assert parse_query("violão de preço baixo").category_ids == frozenset({5})
    assert parse_query("preço do baixo").category_ids == frozenset({2})


def test_category_ids_for_merges_tokens():
    assert category_ids_for(["guitarra", "sopro"]) == frozenset({1, 6, 7})
    assert category_ids_for(["desconhecido"]) == frozenset()


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["cordas"], True),
        (["palheta", "nylon"], True),
        (["7", "cordas"], False),
        (["nylon"], False),
    ],
)
def test_asks_for_accessory_ignores_numeric_context(tokens, expected):
    assert asks_for_accessory(tokens) is expected


def test_with_synonyms_adds_portuguese_words():
    assert with_synonyms({"electric"}) == {"electric", "eletrico", "eletrica"}


def test_token_matches_prefix_only_for_long_alphabetic_tokens():
    assert token_matches("inic", {"iniciantes"})
    assert not token_matches("ini", {"iniciantes"})
    assert not token_matches("2000", {"20000"})


def test_contains_all_tokens_requires_every_token():
    assert contains_all_tokens(["yamaha", "nylon"], {"yamaha", "nylon", "natural"})
    assert not contains_all_tokens(["yamaha", "aco"], {"yamaha", "nylon"})
