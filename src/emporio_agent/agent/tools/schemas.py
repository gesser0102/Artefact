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
    model_validator,
)

from emporio_agent.application.catalog.service import DEFAULT_SEARCH_LIMIT
from emporio_agent.domain.returns import PurchaseChannel, ReturnReason

MAX_SEARCH_LIMIT = 20
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


WholeNumber = Annotated[int, BeforeValidator(reject_boolean)]
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


class OrderIdentityInput(ToolInput):
    model_config = ConfigDict(extra="ignore")

    order_id: WholeNumber
    phone: str = Field(repr=False)


class AssessReturnEligibilityInput(OrderIdentityInput):
    reason: ReturnReason
    channel: PurchaseChannel | None = None
    received_on: IsoDate | None = None
