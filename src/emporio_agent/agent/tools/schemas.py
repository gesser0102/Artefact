import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from emporio_agent.application.catalog.service import DEFAULT_SEARCH_LIMIT
from emporio_agent.application.policies.service import (
    DEFAULT_POLICY_SEARCH_LIMIT,
    MAX_POLICY_SEARCH_LIMIT,
)
from emporio_agent.domain.returns import PurchaseChannel, ReturnReason

MAX_SEARCH_LIMIT = 20
MAX_POLICY_QUERY_LENGTH = 300
MAX_POLICY_SECTION_IDS = 3
MAX_INSTALLMENT_QUOTE_AMOUNT = 1_000_000
MAX_REQUESTED_INSTALLMENTS = 48
ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("boolean is not accepted")
    return value


def numeric_text_to_int(value: object) -> object:
    return int(value) if isinstance(value, str) and value.isdecimal() else value


def require_iso_date_text(value: object) -> object:
    if not isinstance(value, str) or ISO_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("expected YYYY-MM-DD")
    return value


def whole_number_to_text(value: object) -> object:
    checked = reject_boolean(value)
    return str(checked) if isinstance(checked, int) else checked


WholeNumber = Annotated[int, BeforeValidator(reject_boolean)]
PolicyQuery = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_POLICY_QUERY_LENGTH),
]
SectionReference = Annotated[StrictStr, BeforeValidator(whole_number_to_text)]
PhoneText = Annotated[StrictStr, BeforeValidator(whole_number_to_text)]
CategoryReference = Annotated[StrictInt | StrictStr, BeforeValidator(numeric_text_to_int)]
PriceBound = Annotated[Decimal, Field(allow_inf_nan=False)]
IsoDate = Annotated[date, BeforeValidator(require_iso_date_text)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def drop_null_arguments(cls, data: object) -> object:
        if isinstance(data, Mapping):
            return {key: value for key, value in data.items() if value is not None}
        return data


class SearchProductsInput(ToolInput):
    query: str | None = None
    category: CategoryReference | None = None
    min_price: PriceBound | None = None
    max_price: PriceBound | None = None
    electronics: bool | None = None
    include_unavailable: bool = False
    limit: Annotated[WholeNumber, Field(le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT


class GetProductInput(ToolInput):
    product_id: WholeNumber | None = None
    name: str | None = None


class ListCategoriesInput(ToolInput):
    pass


class ListActivePromotionsInput(ToolInput):
    pass


class QuoteInstallmentsInput(ToolInput):
    amount: Annotated[PriceBound, Field(gt=0, le=MAX_INSTALLMENT_QUOTE_AMOUNT)]
    installments: Annotated[WholeNumber, Field(ge=1, le=MAX_REQUESTED_INSTALLMENTS)] | None = None


class OrderIdentityInput(ToolInput):
    model_config = ConfigDict(extra="ignore")

    order_id: WholeNumber
    phone: PhoneText = Field(repr=False)


class SearchPoliciesInput(ToolInput):
    query: PolicyQuery
    limit: Annotated[WholeNumber, Field(ge=1, le=MAX_POLICY_SEARCH_LIMIT)] = (
        DEFAULT_POLICY_SEARCH_LIMIT
    )


class GetPolicySectionsInput(ToolInput):
    section_ids: Annotated[
        list[SectionReference], Field(min_length=1, max_length=MAX_POLICY_SECTION_IDS)
    ]


class AssessReturnEligibilityInput(OrderIdentityInput):
    reason: ReturnReason
    channel: PurchaseChannel | None = None
    received_on: IsoDate | None = None
