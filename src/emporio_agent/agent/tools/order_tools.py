from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from emporio_agent.agent.tools.context import ToolArguments, ToolContext, run_tool
from emporio_agent.agent.tools.schemas import AssessReturnEligibilityInput, OrderIdentityInput
from emporio_agent.agent.tools.serialization import (
    serialize_invalid_received_on,
    serialize_not_verified,
    serialize_order_lookup,
    serialize_return_lookup,
    to_tool_json,
)
from emporio_agent.application.orders.dtos import NotVerified
from emporio_agent.domain.exceptions import InvalidReceivedOnError

GET_ORDER_STATUS = "get_order_status"
ASSESS_RETURN_ELIGIBILITY = "assess_return_eligibility"


def parse_identity(
    context: ToolContext,
    tool_name: str,
    arguments: ToolArguments,
) -> OrderIdentityInput | None:
    try:
        return OrderIdentityInput.model_validate({} if arguments is None else arguments)
    except ValidationError as error:
        context.report_rejected_input(f"tools.{tool_name}", error)
        return None


def get_order_status(context: ToolContext, arguments: ToolArguments = None) -> str:
    identity = parse_identity(context, GET_ORDER_STATUS, arguments)
    if identity is None:
        return to_tool_json(serialize_not_verified())
    return to_tool_json(
        serialize_order_lookup(
            context.orders.find_verified_order(identity.order_id, identity.phone)
        )
    )


def assess_return_eligibility(context: ToolContext, arguments: ToolArguments = None) -> str:
    identity = parse_identity(context, ASSESS_RETURN_ELIGIBILITY, arguments)
    if identity is None or isinstance(
        context.orders.find_verified_order(identity.order_id, identity.phone), NotVerified
    ):
        return to_tool_json(serialize_not_verified())

    def execute(parsed: AssessReturnEligibilityInput) -> Mapping[str, Any]:
        try:
            return serialize_return_lookup(
                context.orders.assess_return(
                    order_id=parsed.order_id,
                    phone=parsed.phone,
                    reason=parsed.reason,
                    channel=parsed.channel,
                    received_on=parsed.received_on,
                )
            )
        except InvalidReceivedOnError as error:
            context.report_rejected_input(f"tools.{ASSESS_RETURN_ELIGIBILITY}", error)
            return serialize_invalid_received_on()

    return run_tool(
        context, ASSESS_RETURN_ELIGIBILITY, AssessReturnEligibilityInput, arguments, execute
    )
