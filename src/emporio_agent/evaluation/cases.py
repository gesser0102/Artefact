import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from emporio_agent.agent.tools.registry import TOOL_HANDLERS
from emporio_agent.application.ports import ErrorReporter
from emporio_agent.domain.exceptions import EvalCaseError

CASES_SCOPE = "evaluation.cases"
CASES_FILE_ENCODING = "utf-8"
CASES_KEY = "cases"
ID_KEY = "id"
CATEGORY_KEY = "category"
DESCRIPTION_KEY = "description"
TURNS_KEY = "turns"
USER_KEY = "user"
EXPECT_KEY = "expect"
TOOLS_ANY_KEY = "tools_any"
TOOLS_ALL_KEY = "tools_all"
TOOLS_NONE_KEY = "tools_none"
CONTAINS_ALL_KEY = "contains_all"
CONTAINS_ANY_KEY = "contains_any"
CONTAINS_NONE_KEY = "contains_none"
NO_CUSTOMER_PII_KEY = "no_customer_pii"
DOCUMENT_KEYS = frozenset({CASES_KEY})
CASE_KEYS = frozenset({ID_KEY, CATEGORY_KEY, DESCRIPTION_KEY, TURNS_KEY})
TURN_KEYS = frozenset({USER_KEY, EXPECT_KEY})
TOOL_KEYS = (TOOLS_ANY_KEY, TOOLS_ALL_KEY, TOOLS_NONE_KEY)
TEXT_KEYS = (CONTAINS_ALL_KEY, CONTAINS_ANY_KEY, CONTAINS_NONE_KEY)
EXPECTATION_KEYS = frozenset({*TOOL_KEYS, *TEXT_KEYS, NO_CUSTOMER_PII_KEY})
KNOWN_TOOL_NAMES = frozenset(TOOL_HANDLERS)


@dataclass(frozen=True)
class TurnExpectation:
    tools_any: tuple[str, ...] = ()
    tools_all: tuple[str, ...] = ()
    tools_none: tuple[str, ...] = ()
    contains_all: tuple[str, ...] = ()
    contains_any: tuple[str, ...] = ()
    contains_none: tuple[str, ...] = ()
    no_customer_pii: bool = True

    @property
    def has_tool_expectations(self) -> bool:
        return bool(self.tools_any or self.tools_all or self.tools_none)


@dataclass(frozen=True)
class EvalTurn:
    user: str
    expect: TurnExpectation


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    description: str
    turns: tuple[EvalTurn, ...]


def fail(location: str, problem: str) -> NoReturn:
    raise EvalCaseError(f"{location}: {problem}")


def require_mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        fail(location, "expected an object")
    return value


def require_keys(
    mapping: Mapping[str, Any],
    allowed: frozenset[str],
    required: frozenset[str],
    location: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        fail(location, f"unknown keys {unknown}")
    missing = sorted(required - set(mapping))
    if missing:
        fail(location, f"missing keys {missing}")


def require_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(location, "expected a non-empty string")
    return value


def require_texts(value: object, location: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        fail(location, "expected a list of strings")
    return tuple(require_text(item, location) for item in value)


def require_known_tools(names: Sequence[str], location: str) -> None:
    unknown = sorted(set(names) - KNOWN_TOOL_NAMES)
    if unknown:
        fail(location, f"unknown tools {unknown}; known tools {sorted(KNOWN_TOOL_NAMES)}")


def parse_expectation(raw: object, location: str) -> TurnExpectation:
    mapping = require_mapping(raw, location)
    require_keys(mapping, EXPECTATION_KEYS, frozenset(), location)
    texts = {
        key: require_texts(mapping.get(key, []), f"{location}.{key}")
        for key in (*TOOL_KEYS, *TEXT_KEYS)
    }
    require_known_tools([name for key in TOOL_KEYS for name in texts[key]], location)
    contradictory = sorted(set(texts[TOOLS_ALL_KEY]) & set(texts[TOOLS_NONE_KEY]))
    if contradictory:
        fail(location, f"tools both required and forbidden {contradictory}")
    no_customer_pii = mapping.get(NO_CUSTOMER_PII_KEY, True)
    if not isinstance(no_customer_pii, bool):
        fail(f"{location}.{NO_CUSTOMER_PII_KEY}", "expected a boolean")
    return TurnExpectation(
        tools_any=texts[TOOLS_ANY_KEY],
        tools_all=texts[TOOLS_ALL_KEY],
        tools_none=texts[TOOLS_NONE_KEY],
        contains_all=texts[CONTAINS_ALL_KEY],
        contains_any=texts[CONTAINS_ANY_KEY],
        contains_none=texts[CONTAINS_NONE_KEY],
        no_customer_pii=no_customer_pii,
    )


def parse_turn(raw: object, location: str) -> EvalTurn:
    mapping = require_mapping(raw, location)
    require_keys(mapping, TURN_KEYS, frozenset({USER_KEY}), location)
    return EvalTurn(
        user=require_text(mapping[USER_KEY], f"{location}.{USER_KEY}"),
        expect=parse_expectation(mapping.get(EXPECT_KEY, {}), f"{location}.{EXPECT_KEY}"),
    )


def parse_case(raw: object, location: str) -> EvalCase:
    mapping = require_mapping(raw, location)
    require_keys(mapping, CASE_KEYS, CASE_KEYS, location)
    case_id = require_text(mapping[ID_KEY], f"{location}.{ID_KEY}")
    case_location = f"case {case_id!r}"
    raw_turns = mapping[TURNS_KEY]
    if not isinstance(raw_turns, list) or not raw_turns:
        fail(case_location, "expected a non-empty list of turns")
    return EvalCase(
        case_id=case_id,
        category=require_text(mapping[CATEGORY_KEY], f"{case_location}.{CATEGORY_KEY}"),
        description=require_text(mapping[DESCRIPTION_KEY], f"{case_location}.{DESCRIPTION_KEY}"),
        turns=tuple(
            parse_turn(turn, f"{case_location} turn {number}")
            for number, turn in enumerate(raw_turns, start=1)
        ),
    )


def parse_cases(document: object) -> tuple[EvalCase, ...]:
    mapping = require_mapping(document, "document")
    require_keys(mapping, DOCUMENT_KEYS, DOCUMENT_KEYS, "document")
    raw_cases = mapping[CASES_KEY]
    if not isinstance(raw_cases, list) or not raw_cases:
        fail("document", "expected a non-empty list of cases")
    cases = tuple(
        parse_case(raw, f"case #{number}") for number, raw in enumerate(raw_cases, start=1)
    )
    case_ids = [case.case_id for case in cases]
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicates:
        fail("document", f"duplicate case ids {duplicates}")
    return cases


def read_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding=CASES_FILE_ENCODING))
    except (OSError, ValueError) as error:
        raise EvalCaseError(f"could not read cases file {path}") from error


def load_cases(path: Path, report_error: ErrorReporter) -> tuple[EvalCase, ...]:
    try:
        return parse_cases(read_document(path))
    except EvalCaseError as error:
        report_error(CASES_SCOPE, error, path=str(path))
        raise


def select_cases(
    cases: Sequence[EvalCase],
    only: Sequence[str] = (),
    category: str | None = None,
) -> tuple[EvalCase, ...]:
    unknown = sorted(set(only) - {case.case_id for case in cases})
    if unknown:
        raise EvalCaseError(f"unknown case ids {unknown}")
    selected = tuple(
        case
        for case in cases
        if (not only or case.case_id in only) and (category is None or case.category == category)
    )
    if not selected:
        raise EvalCaseError("no cases match the selection")
    return selected
