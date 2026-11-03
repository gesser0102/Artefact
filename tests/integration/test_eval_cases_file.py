from collections import Counter
from pathlib import Path

import pytest

from emporio_agent.evaluation.cases import KNOWN_TOOL_NAMES, load_cases
from emporio_agent.evaluation.checks import phone_digit_runs
from emporio_agent.evaluation.resolver import EvalDataResolver, placeholders_in
from fakes import RecordingErrorReporter

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "cases.json"
MIN_CASES = 28
MAX_CASES = 32
MIN_CASES_PER_CATEGORY = {
    "catalog": 6,
    "policy": 6,
    "installments": 3,
    "orders": 5,
    "returns": 3,
    "safety": 5,
}


@pytest.fixture(scope="module")
def cases():
    return load_cases(CASES_PATH, RecordingErrorReporter())


@pytest.fixture(scope="module")
def resolver(repository):
    return EvalDataResolver(repository, repository.list_customers())


def test_case_count_is_within_bounds(cases):
    assert MIN_CASES <= len(cases) <= MAX_CASES


def test_every_category_has_the_minimum_number_of_cases(cases):
    counts = Counter(case.category for case in cases)

    assert set(counts) == set(MIN_CASES_PER_CATEGORY)
    for category, minimum in MIN_CASES_PER_CATEGORY.items():
        assert counts[category] >= minimum, category


def test_every_expected_tool_exists(cases):
    expected = {
        name
        for case in cases
        for turn in case.turns
        for name in (*turn.expect.tools_any, *turn.expect.tools_all, *turn.expect.tools_none)
    }

    assert expected <= KNOWN_TOOL_NAMES


def test_every_placeholder_resolves_against_the_real_data(cases, resolver):
    resolver.validate(cases)

    assert any(placeholders_in(turn.user) for case in cases for turn in case.turns)


def test_the_cases_file_holds_no_real_customer_phone_or_email(resolver):
    text = CASES_PATH.read_text(encoding="utf-8")
    runs = phone_digit_runs(text)

    assert not [s for s in resolver.contacts.phone_suffixes if any(s in run for run in runs)]
    assert not [email for email in resolver.contacts.emails if email in text.casefold()]


def test_every_turn_checks_customer_pii(cases):
    assert all(turn.expect.no_customer_pii for case in cases for turn in case.turns)
