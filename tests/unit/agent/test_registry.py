import pytest

from emporio_agent.agent.tools.registry import (
    ORDER_TOOL_NAMES,
    TOOL_HANDLERS,
    TOOL_SPECS,
)
from emporio_agent.agent.tools.schemas import (
    AssessReturnEligibilityInput,
    GetPolicySectionsInput,
    GetProductInput,
    ListActivePromotionsInput,
    ListCategoriesInput,
    OrderIdentityInput,
    QuoteInstallmentsInput,
    SearchPoliciesInput,
    SearchProductsInput,
    ToolInput,
)

INPUT_MODELS: dict[str, type[ToolInput]] = {
    "search_products": SearchProductsInput,
    "get_product": GetProductInput,
    "list_categories": ListCategoriesInput,
    "list_active_promotions": ListActivePromotionsInput,
    "quote_installments": QuoteInstallmentsInput,
    "get_order_status": OrderIdentityInput,
    "assess_return_eligibility": AssessReturnEligibilityInput,
    "search_policies": SearchPoliciesInput,
    "get_policy_sections": GetPolicySectionsInput,
}
SPECS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def test_tool_names_are_unique_and_complete():
    names = [spec.name for spec in TOOL_SPECS]

    assert len(names) == len(set(names))
    assert set(names) == set(INPUT_MODELS)


def test_every_spec_has_a_handler_and_vice_versa():
    assert set(TOOL_HANDLERS) == set(SPECS_BY_NAME)


@pytest.mark.parametrize("name", list(INPUT_MODELS))
def test_schema_properties_match_the_input_model(name):
    model = INPUT_MODELS[name]
    parameters = SPECS_BY_NAME[name].parameters

    assert parameters["type"] == "object"
    assert set(parameters["properties"]) == set(model.model_fields)
    assert set(parameters.get("required", [])) == {
        field for field, info in model.model_fields.items() if info.is_required()
    }


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda spec: spec.name)
def test_descriptions_are_concise(spec):
    assert 20 <= len(spec.description) <= 260


def test_order_tools_tell_the_model_never_to_invent_identity():
    order_status = SPECS_BY_NAME["get_order_status"].description

    assert sorted(ORDER_TOOL_NAMES) == ["assess_return_eligibility", "get_order_status"]
    assert "order number AND the registered phone" in order_status
    assert "never invent" in order_status
    assert "get_order_status" in SPECS_BY_NAME["assess_return_eligibility"].description


def test_return_schema_enums_follow_the_domain():
    properties = SPECS_BY_NAME["assess_return_eligibility"].parameters["properties"]

    assert properties["reason"]["enum"] == ["regret", "defect", "preference"]
    assert properties["channel"]["enum"] == ["online", "in_store"]


def test_installment_schema_bounds_follow_the_input_model():
    properties = SPECS_BY_NAME["quote_installments"].parameters["properties"]

    assert properties["amount"]["type"] == "number"
    assert properties["installments"]["type"] == "integer"
    assert properties["installments"]["maximum"] == 48
    assert "instead of calculating" in SPECS_BY_NAME["quote_installments"].description
