import pytest

from emporio_agent.application.policies.search import (
    BM25_B,
    BM25_K1,
    POLICY_STOPWORDS,
    RELATIVE_SCORE_FLOOR,
    SECTION_ALIASES,
    STEM_LENGTH,
    alias_terms,
    document_terms,
    rank_sections,
    search_terms,
    stem,
)
from emporio_agent.application.text import tokenize
from fakes import make_section

PAYMENTS = make_section("3", "Formas de Pagamento", "Aceitamos PIX e boleto.")
INSTALLMENTS = make_section(
    "3.1", "Regras de Parcelamento", "Até 12x sem juros no cartão.", parent=PAYMENTS
)
HOURS = make_section("2", "Horário de Funcionamento", "Segunda a sexta, das 9h às 18h.")
SHIPPING = make_section("5", "Frete e Entregas")
SECTIONS = (HOURS, PAYMENTS, INSTALLMENTS, SHIPPING)


def ranked_ids(query: str, sections=SECTIONS, limit: int = 5) -> list[str]:
    return [section.section_id for section in rank_sections(query, sections, limit)]


def test_bm25_parameters_are_the_contract_values():
    assert (BM25_K1, BM25_B, RELATIVE_SCORE_FLOOR, STEM_LENGTH) == (1.2, 0.75, 0.35, 5)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("parcelamento", "parce"),
        ("parcelar", "parce"),
        ("parce", "parce"),
        ("pix", "pix"),
        ("juros", "juros"),
        ("12", "12"),
        ("123456", "123456"),
    ],
)
def test_stem_truncates_only_long_alphabetic_tokens(token, expected):
    assert stem(token) == expected


def test_search_terms_drop_stopwords_and_stem():
    assert search_terms("Qual o horário que vocês abrem no sábado?") == ["horar", "abrem", "sabad"]


@pytest.mark.parametrize("query", ["oi", "obrigado", "qual o que", "vcs", "", "?!"])
def test_filler_only_queries_have_no_terms(query):
    assert search_terms(query) == []


def test_catalog_price_words_are_not_policy_stopwords():
    assert POLICY_STOPWORDS.isdisjoint({"preco", "valor", "custo", "barato"})


def test_stopwords_are_already_normalized_tokens():
    assert all(tokenize(word) == [word] for word in POLICY_STOPWORDS)


def test_alias_terms_are_tokenized_and_stemmed():
    assert alias_terms("4.1")[-4:] == ["dinhe", "volta", "tempo", "prazo"]
    assert alias_terms("missing") == []


def test_document_terms_weight_title_and_include_parent_and_aliases():
    terms = document_terms(INSTALLMENTS)

    assert terms.count("regra") == 2
    assert terms.count("pagam") >= 1
    assert "vezes" in terms
    assert "carta" in terms


def test_aliases_are_keyed_by_section_ids_and_non_empty():
    assert all(key.replace(".", "").isdigit() and SECTION_ALIASES[key] for key in SECTION_ALIASES)


def test_aliases_are_scoped_to_their_section_id():
    unaliased = make_section("20", "Assunto", "texto")
    aliased = make_section("2", "Assunto", "texto")

    assert ranked_ids("domingo", (unaliased, aliased)) == ["2"]


def test_aliases_route_customer_vocabulary():
    assert ranked_ids("vcs abrem domingo?")[:1] == ["2"]
    assert ranked_ids("posso parcelar em 10x?")[:1] == ["3.1"]


def test_title_match_outranks_body_only_match():
    sections = (
        make_section("20", "Outro Assunto", "menciona garantia uma vez"),
        make_section("21", "Garantia", "texto qualquer"),
    )

    assert ranked_ids("garantia", sections) == ["21", "20"]


def test_ties_follow_manual_order():
    sections = tuple(make_section(str(number), "Entregas", "entregas") for number in (30, 20, 40))

    assert ranked_ids("entregas", sections) == ["30", "20", "40"]


def test_weak_matches_below_relative_floor_are_dropped():
    sections = (
        make_section("20", "Garantia Legal", "garantia garantia garantia legal do fabricante"),
        make_section("21", "Outro", " ".join(["texto"] * 60) + " fabricante"),
        make_section("22", "Mais Um", "texto sem relação"),
    )

    assert ranked_ids("garantia legal fabricante", sections) == ["20"]


def test_sections_without_body_are_never_returned():
    assert "5" not in ranked_ids("frete e entregas")


def test_out_of_scope_query_returns_nothing():
    assert ranked_ids("receita de bolo de cenoura") == []


def test_limit_caps_the_result():
    assert len(ranked_ids("pagamento parcelamento pix", limit=1)) == 1


def test_empty_inputs_return_nothing():
    assert ranked_ids("pix", sections=()) == []
    assert ranked_ids("   ") == []
