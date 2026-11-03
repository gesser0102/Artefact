from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from emporio_agent.agent.tools.schemas import (
    MAX_POLICY_QUERY_LENGTH,
    MAX_POLICY_SECTION_IDS,
    MAX_SEARCH_LIMIT,
    AssessReturnEligibilityInput,
    GetPolicySectionsInput,
    GetProductInput,
    ListActivePromotionsInput,
    ListCategoriesInput,
    OrderIdentityInput,
    QuoteInstallmentsInput,
    SearchPoliciesInput,
    SearchProductsInput,
)
from emporio_agent.application.catalog.service import DEFAULT_SEARCH_LIMIT
from emporio_agent.application.policies.service import (
    DEFAULT_POLICY_SEARCH_LIMIT,
    MAX_POLICY_SEARCH_LIMIT,
)
from emporio_agent.domain.returns import PurchaseChannel, ReturnReason


@pytest.mark.parametrize(
    ("raw", "expected"), [("95", 95), (" 95 ", 95), ("0095", 95), (95, 95), ("-95", -95)]
)
def test_product_id_is_coerced_to_int(raw, expected):
    assert GetProductInput.model_validate({"product_id": raw}).product_id == expected


@pytest.mark.parametrize("raw", ["abc", "", "²", 95.5, True, False, ["95"]])
def test_product_id_rejects_non_integers(raw):
    with pytest.raises(ValidationError):
        GetProductInput.model_validate({"product_id": raw})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1000", Decimal("1000")),
        (" 99.90 ", Decimal("99.90")),
        (1000, Decimal("1000")),
        (323.1, Decimal("323.1")),
    ],
)
def test_price_bound_is_coerced_to_decimal(raw, expected):
    parsed = SearchProductsInput.model_validate({"max_price": raw})

    assert isinstance(parsed.max_price, Decimal)
    assert parsed.max_price == expected


@pytest.mark.parametrize("raw", ["abc", "", "NaN", "Infinity", "-Infinity", True, float("inf")])
@pytest.mark.parametrize("field", ["min_price", "max_price"])
def test_price_bound_rejects_invalid_values(field, raw):
    with pytest.raises(ValidationError):
        SearchProductsInput.model_validate({field: raw})


@pytest.mark.parametrize(
    ("raw", "expected"), [("5", 5), (5, 5), ("05", 5), ("violões", "violões"), (" 5 ", " 5 ")]
)
def test_category_keeps_names_and_coerces_numeric_text(raw, expected):
    assert SearchProductsInput.model_validate({"category": raw}).category == expected


@pytest.mark.parametrize("raw", [True, 5.0, ["5"], "9" * 5000])
def test_category_rejects_other_types(raw):
    with pytest.raises(ValidationError):
        SearchProductsInput.model_validate({"category": raw})


def test_search_defaults():
    parsed = SearchProductsInput.model_validate({})

    assert parsed.limit == DEFAULT_SEARCH_LIMIT
    assert parsed.include_unavailable is False
    assert parsed.query is None


def test_limit_accepts_numeric_text_up_to_maximum():
    assert MAX_SEARCH_LIMIT == 20
    assert SearchProductsInput.model_validate({"limit": "20"}).limit == 20


@pytest.mark.parametrize("raw", [21, "21", 200, True, "x"])
def test_limit_rejects_values_above_maximum_and_non_integers(raw):
    with pytest.raises(ValidationError):
        SearchProductsInput.model_validate({"limit": raw})


def test_limit_keeps_accepting_non_positive_values():
    assert SearchProductsInput.model_validate({"limit": 0}).limit == 0
    assert SearchProductsInput.model_validate({"limit": -1}).limit == -1


def test_null_arguments_fall_back_to_defaults():
    parsed = SearchProductsInput.model_validate(
        {"query": None, "include_unavailable": None, "limit": None}
    )

    assert parsed.include_unavailable is False
    assert parsed.limit == DEFAULT_SEARCH_LIMIT


@pytest.mark.parametrize(
    "model",
    [
        SearchProductsInput,
        GetProductInput,
        ListCategoriesInput,
        ListActivePromotionsInput,
        SearchPoliciesInput,
        GetPolicySectionsInput,
        QuoteInstallmentsInput,
    ],
)
def test_every_input_rejects_unknown_arguments(model):
    with pytest.raises(ValidationError):
        model.model_validate({"brand": "Yamaha"})


def test_order_identity_ignores_unknown_keys_so_they_never_echo_in_errors():
    with pytest.raises(ValidationError) as raised:
        OrderIdentityInput.model_validate({"order_id": "abc", "phone": "x", "(11) 91234-5678": 1})

    assert "91234" not in str(raised.value)


def test_order_identity_hides_the_phone_from_repr_and_errors():
    parsed = OrderIdentityInput.model_validate({"order_id": 1, "phone": "(11) 91234-5678"})

    assert "91234" not in repr(parsed)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (11912345678, "11912345678"),
        ("11912345678", "11912345678"),
        (5511912345678, "5511912345678"),
    ],
)
def test_phone_as_json_integer_becomes_its_decimal_text(raw, expected):
    assert OrderIdentityInput.model_validate({"order_id": 1, "phone": raw}).phone == expected


@pytest.mark.parametrize(
    "raw", [True, False, 1.5, ["11912345678"], {"telefone": "11912345678"}, None]
)
def test_phone_rejects_other_types_without_echoing_them(raw):
    with pytest.raises(ValidationError) as raised:
        OrderIdentityInput.model_validate({"order_id": 1, "phone": raw})

    [error] = raised.value.errors(include_url=False, include_context=False, include_input=False)
    assert error["loc"] == ("phone",)
    assert "11912345678" not in str(raised.value)


@pytest.mark.parametrize("arguments", [None, [], "texto", 7])
def test_order_identity_rejects_non_object_arguments(arguments):
    with pytest.raises(ValidationError):
        OrderIdentityInput.model_validate(arguments)


def test_return_input_parses_enums_and_iso_date():
    parsed = AssessReturnEligibilityInput.model_validate(
        {
            "order_id": "1",
            "phone": "x",
            "reason": "regret",
            "channel": "in_store",
            "received_on": "2026-03-01",
        }
    )

    assert parsed.order_id == 1
    assert parsed.reason is ReturnReason.REGRET
    assert parsed.channel is PurchaseChannel.IN_STORE
    assert parsed.received_on == date(2026, 3, 1)


@pytest.mark.parametrize(
    "raw",
    [
        "(11) 91234-5678",
        "01/03/2026",
        "20260301",
        "1767225600",
        "",
        20260301,
        1767225600,
        True,
    ],
)
def test_received_on_only_accepts_iso_text_and_never_echoes_it(raw):
    with pytest.raises(ValidationError) as raised:
        AssessReturnEligibilityInput.model_validate(
            {"order_id": 1, "phone": "x", "reason": "defect", "received_on": raw}
        )

    assert "91234" not in str(raised.value)
    assert "91234" not in str(raised.value.errors(include_input=False, include_context=False))


def test_policy_search_defaults_and_strips_the_query():
    parsed = SearchPoliciesInput.model_validate({"query": "  frete grátis  "})

    assert parsed.query == "frete grátis"
    assert parsed.limit == DEFAULT_POLICY_SEARCH_LIMIT


def test_policy_search_null_limit_falls_back_to_default():
    parsed = SearchPoliciesInput.model_validate({"query": "x", "limit": None})

    assert parsed.limit == DEFAULT_POLICY_SEARCH_LIMIT


@pytest.mark.parametrize(("raw", "expected"), [(1, 1), ("5", 5), (" 2 ", 2)])
def test_policy_search_limit_accepts_whole_numbers_in_range(raw, expected):
    assert SearchPoliciesInput.model_validate({"query": "x", "limit": raw}).limit == expected


@pytest.mark.parametrize("raw", [0, -1, MAX_POLICY_SEARCH_LIMIT + 1, "6", True, 2.5, "x"])
def test_policy_search_limit_rejects_values_out_of_range(raw):
    with pytest.raises(ValidationError):
        SearchPoliciesInput.model_validate({"query": "x", "limit": raw})


def test_policy_query_accepts_the_maximum_length_after_strip():
    query = "a" * MAX_POLICY_QUERY_LENGTH

    assert SearchPoliciesInput.model_validate({"query": f"  {query}  "}).query == query


@pytest.mark.parametrize(
    "raw", ["", "   ", "a" * (MAX_POLICY_QUERY_LENGTH + 1), 7, True, ["frete"], None]
)
def test_policy_query_rejects_blank_long_or_non_text(raw):
    with pytest.raises(ValidationError):
        SearchPoliciesInput.model_validate({"query": raw})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["4.2"], ["4.2"]),
        ([4], ["4"]),
        (["seção 4", 10, " 3.1 "], ["seção 4", "10", " 3.1 "]),
    ],
)
def test_section_ids_accept_text_and_coerce_integers(raw, expected):
    assert GetPolicySectionsInput.model_validate({"section_ids": raw}).section_ids == expected


@pytest.mark.parametrize(
    "raw",
    [
        [],
        ["1"] * (MAX_POLICY_SECTION_IDS + 1),
        [True],
        [False, "1"],
        [4.2],
        [None],
        [["4"]],
        "4.2",
        4,
        None,
    ],
)
def test_section_ids_reject_booleans_floats_and_bad_sizes(raw):
    with pytest.raises(ValidationError):
        GetPolicySectionsInput.model_validate({"section_ids": raw})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600", Decimal("600")),
        (" 49.90 ", Decimal("49.90")),
        (1200, Decimal("1200")),
        (0.01, Decimal("0.01")),
    ],
)
def test_installment_amount_is_coerced_to_decimal(raw, expected):
    parsed = QuoteInstallmentsInput.model_validate({"amount": raw})

    assert isinstance(parsed.amount, Decimal)
    assert parsed.amount == expected
    assert parsed.installments is None


@pytest.mark.parametrize(
    "raw", [0, "0", -1, "-50", 1_000_001, "NaN", "Infinity", "abc", "", True, None, ["600"]]
)
def test_installment_amount_rejects_non_positive_huge_or_non_numeric(raw):
    with pytest.raises(ValidationError):
        QuoteInstallmentsInput.model_validate({"amount": raw})


@pytest.mark.parametrize(("raw", "expected"), [(1, 1), ("18", 18), (48, 48), (None, None)])
def test_requested_installments_accept_whole_numbers_up_to_48(raw, expected):
    parsed = QuoteInstallmentsInput.model_validate({"amount": 600, "installments": raw})

    assert parsed.installments == expected


@pytest.mark.parametrize("raw", [0, -3, 49, True, 2.5, "x"])
def test_requested_installments_reject_out_of_range_or_non_integers(raw):
    with pytest.raises(ValidationError):
        QuoteInstallmentsInput.model_validate({"amount": 600, "installments": raw})
