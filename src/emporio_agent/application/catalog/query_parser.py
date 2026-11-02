import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

MIN_PREFIX_TOKEN_LENGTH = 4
TOKEN_PATTERN = re.compile(r"[a-z]+|[0-9]+")
STOPWORDS = frozenset(
    {
        "a",
        "as",
        "o",
        "os",
        "um",
        "uma",
        "e",
        "ou",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "para",
        "pra",
        "com",
        "mais",
        "bom",
        "boa",
        "bons",
        "boas",
        "preco",
        "precos",
        "valor",
        "custo",
        "barato",
        "barata",
        "baratos",
        "baratas",
    }
)
PRICE_TOKENS = frozenset({"preco", "precos", "valor", "custo"})
PRICE_ADJECTIVE_TOKEN = "baixo"
PORTUGUESE_SYNONYMS_BY_WORD = {"electric": frozenset({"eletrico", "eletrica"})}
ACCESSORY_TOKENS = frozenset(
    {
        "corda",
        "cordas",
        "palheta",
        "palhetas",
        "cabo",
        "cabos",
        "case",
        "cases",
        "capa",
        "capas",
        "pedal",
        "pedais",
        "amplificador",
        "amplificadores",
    }
)
CATEGORY_IDS_BY_TOKEN = {
    "guitarra": frozenset({1}),
    "guitarras": frozenset({1}),
    "baixo": frozenset({2}),
    "baixos": frozenset({2}),
    "contrabaixo": frozenset({2}),
    "contrabaixos": frozenset({2}),
    "bateria": frozenset({3}),
    "baterias": frozenset({3}),
    "percussao": frozenset({3}),
    "percussoes": frozenset({3}),
    "teclado": frozenset({4}),
    "teclados": frozenset({4}),
    "piano": frozenset({4}),
    "pianos": frozenset({4}),
    "violao": frozenset({5}),
    "violoes": frozenset({5}),
    "sopro": frozenset({6, 7}),
    "sopros": frozenset({6, 7}),
    "orquestral": frozenset({8}),
    "orquestrais": frozenset({8}),
    "ukulele": frozenset({9}),
    "ukuleles": frozenset({9}),
    "ukelele": frozenset({9}),
    "ukeleles": frozenset({9}),
    "uquelele": frozenset({9}),
    "uqueleles": frozenset({9}),
}


@dataclass(frozen=True)
class ParsedQuery:
    category_ids: frozenset[int]
    text_tokens: tuple[str, ...]


def tokenize(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return TOKEN_PATTERN.findall(unaccented)


def without_stopwords(tokens: Iterable[str]) -> list[str]:
    return [token for token in tokens if token not in STOPWORDS]


def without_price_adjective(tokens: list[str]) -> list[str]:
    names_another_category = any(
        token in CATEGORY_IDS_BY_TOKEN and token != PRICE_ADJECTIVE_TOKEN for token in tokens
    )
    if names_another_category and not PRICE_TOKENS.isdisjoint(tokens):
        return [token for token in tokens if token != PRICE_ADJECTIVE_TOKEN]
    return tokens


def category_ids_for(tokens: Iterable[str]) -> frozenset[int]:
    empty: frozenset[int] = frozenset()
    return empty.union(*(CATEGORY_IDS_BY_TOKEN.get(token, empty) for token in tokens))


def parse_query(query: str | None) -> ParsedQuery:
    tokens = without_stopwords(without_price_adjective(tokenize(query or "")))
    return ParsedQuery(
        category_ids=category_ids_for(tokens),
        text_tokens=tuple(token for token in tokens if token not in CATEGORY_IDS_BY_TOKEN),
    )


def asks_for_accessory(text_tokens: Iterable[str]) -> bool:
    tokens = tuple(text_tokens)
    return not ACCESSORY_TOKENS.isdisjoint(tokens) and not any(token.isdigit() for token in tokens)


def with_synonyms(words: set[str]) -> set[str]:
    empty: frozenset[str] = frozenset()
    return words.union(*(PORTUGUESE_SYNONYMS_BY_WORD.get(word, empty) for word in words))


def token_matches(token: str, words: set[str]) -> bool:
    if token in words:
        return True
    return (
        len(token) >= MIN_PREFIX_TOKEN_LENGTH
        and token.isalpha()
        and any(word.startswith(token) for word in words)
    )


def contains_all_tokens(tokens: Iterable[str], words: set[str]) -> bool:
    return all(token_matches(token, words) for token in tokens)
