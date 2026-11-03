from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from emporio_agent.agent.tools.context import ToolArguments, ToolContext, run_tool
from emporio_agent.agent.tools.schemas import AssessReturnEligibilityInput, OrderIdentityInput
from emporio_agent.agent.tools.serialization import (
    serialize_invalid_arguments,
    serialize_invalid_received_on,
    serialize_not_verified,
    serialize_order_lookup,
    serialize_return_lookup,
    to_tool_json,
)
from emporio_agent.application.orders.dtos import NotVerified, OrderLookup
from emporio_agent.domain.exceptions import InvalidReceivedOnError

GET_ORDER_STATUS = "get_order_status"
ASSESS_RETURN_ELIGIBILITY = "assess_return_eligibility"


def find_order(context: ToolContext, identity: OrderIdentityInput) -> OrderLookup:
    return context.orders.find_verified_order(identity.order_id, identity.phone)


def identity_gate_output(
    context: ToolContext,
    tool_name: str,
    arguments: ToolArguments,
) -> str | None:
    try:
        identity = OrderIdentityInput.model_validate({} if arguments is None else arguments)
    except ValidationError as error:
        context.report_rejected_input(f"tools.{tool_name}", error)
        return to_tool_json(serialize_invalid_arguments(error))
    if isinstance(find_order(context, identity), NotVerified):
        return to_tool_json(serialize_not_verified())
    return None


def get_order_status(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(identity: OrderIdentityInput) -> Mapping[str, Any]:
        return serialize_order_lookup(find_order(context, identity))

    return run_tool(context, GET_ORDER_STATUS, OrderIdentityInput, arguments, execute)


def assess_return_eligibility(context: ToolContext, arguments: ToolArguments = None) -> str:
    gate_output = identity_gate_output(context, ASSESS_RETURN_ELIGIBILITY, arguments)
    if gate_output is not None:
        return gate_output

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
