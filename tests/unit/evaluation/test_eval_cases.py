import json

import pytest

from emporio_agent.domain.exceptions import EvalCaseError
from emporio_agent.evaluation.cases import (
    CASES_SCOPE,
    EvalCase,
    EvalTurn,
    TurnExpectation,
    load_cases,
    parse_cases,
    select_cases,
)
from fakes import RecordingErrorReporter


def case(case_id="c1", category="catalog", turns=None, **extra):
    return {
        "id": case_id,
        "category": category,
        "description": "descrição",
        "turns": [{"user": "oi"}] if turns is None else turns,
        **extra,
    }


def document(*cases):
    return {"cases": list(cases)}


def test_parses_cases_with_defaults_and_expectations():
    raw = case(
        turns=[
            {"user": "oi"},
            {
                "user": "quanto custa?",
                "expect": {
                    "tools_any": ["search_products", "get_product"],
                    "tools_none": ["get_order_status"],
                    "contains_all": ["R$"],
                    "contains_none": ["grátis"],
                    "no_customer_pii": False,
                },
            },
        ]
    )

    (parsed,) = parse_cases(document(raw))

    assert parsed == EvalCase(
        case_id="c1",
        category="catalog",
        description="descrição",
        turns=(
            EvalTurn("oi", TurnExpectation()),
            EvalTurn(
                "quanto custa?",
                TurnExpectation(
                    tools_any=("search_products", "get_product"),
                    tools_none=("get_order_status",),
                    contains_all=("R$",),
                    contains_none=("grátis",),
                    no_customer_pii=False,
                ),
            ),
        ),
    )
    assert TurnExpectation().no_customer_pii is True
    assert parsed.turns[1].expect.has_tool_expectations
    assert not parsed.turns[0].expect.has_tool_expectations


def test_unknown_tool_names_are_listed():
    raw = case(
        turns=[{"user": "oi", "expect": {"tools_all": ["get_order", "teleport", "get_product"]}}]
    )

    with pytest.raises(EvalCaseError, match=r"unknown tools \['get_order', 'teleport'\]"):
        parse_cases(document(raw))


@pytest.mark.parametrize(
    ("raw_document", "message"),
    [
        (document(case(colour="azul")), r"unknown keys \['colour'\]"),
        (document(case(turns=[{"user": "oi", "extra": 1}])), r"unknown keys \['extra'\]"),
        (
            document(case(turns=[{"user": "oi", "expect": {"contains": ["x"]}}])),
            r"unknown keys \['contains'\]",
        ),
        ({"cases": [], "version": 1}, r"unknown keys \['version'\]"),
        (document(case(turns=[])), "non-empty list of turns"),
        (document(), "non-empty list of cases"),
        ({}, r"missing keys \['cases'\]"),
        ([], "expected an object"),
        (document({"id": "c1", "category": "x", "turns": [{"user": "a"}]}), "missing keys"),
        (document(case(turns=[{"user": "  "}])), "non-empty string"),
        (document(case(turns=[{"expect": {}}])), r"missing keys \['user'\]"),
        (
            document(case(turns=[{"user": "a", "expect": {"contains_any": "x"}}])),
            "list of strings",
        ),
        (
            document(case(turns=[{"user": "a", "expect": {"no_customer_pii": "sim"}}])),
            "boolean",
        ),
        (
            document(
                case(
                    turns=[
                        {
                            "user": "a",
                            "expect": {
                                "tools_all": ["get_product"],
                                "tools_none": ["get_product"],
                            },
                        }
                    ]
                )
            ),
            "both required and forbidden",
        ),
        (document(case("dup"), case("dup")), r"duplicate case ids \['dup'\]"),
    ],
)
def test_invalid_documents_are_rejected(raw_document, message):
    with pytest.raises(EvalCaseError, match=message):
        parse_cases(raw_document)


def test_load_cases_reads_utf8_json(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(document(case(turns=[{"user": "violão?"}]))), encoding="utf-8")

    (loaded,) = load_cases(path, RecordingErrorReporter())

    assert loaded.turns[0].user == "violão?"


@pytest.mark.parametrize("content", [None, "{ não é json", json.dumps(document())])
def test_load_cases_reports_and_raises_domain_error(tmp_path, content):
    path = tmp_path / "cases.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    reporter = RecordingErrorReporter()

    with pytest.raises(EvalCaseError):
        load_cases(path, reporter)

    assert [scope for scope, _ in reporter.reports] == [CASES_SCOPE]
    assert isinstance(reporter.reports[0][1], EvalCaseError)


CASES = parse_cases(document(case("a", "catalog"), case("b", "policy"), case("c", "catalog")))


def test_select_cases_without_filters_keeps_everything():
    assert select_cases(CASES) == CASES


def test_select_cases_by_ids_and_category():
    assert [c.case_id for c in select_cases(CASES, only=("c", "a"))] == ["a", "c"]
    assert [c.case_id for c in select_cases(CASES, category="catalog")] == ["a", "c"]
    assert [c.case_id for c in select_cases(CASES, ("a", "b"), "policy")] == ["b"]


def test_select_cases_rejects_unknown_ids_and_empty_selections():
    with pytest.raises(EvalCaseError, match=r"unknown case ids \['zzz'\]"):
        select_cases(CASES, only=("a", "zzz"))
    with pytest.raises(EvalCaseError, match="no cases match"):
        select_cases(CASES, category="safety")
