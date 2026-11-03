from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from emporio_agent.agent.tools.schemas import ToolInput
from emporio_agent.agent.tools.serialization import serialize_invalid_arguments, to_tool_json
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.application.ports import ErrorReporter

type ToolArguments = Mapping[str, object] | None


@dataclass(frozen=True)
class ToolContext:
    catalog: CatalogService
    orders: OrderService
    policies: PolicyService
    report_error: ErrorReporter


def run_tool[Input: ToolInput](
    context: ToolContext,
    tool_name: str,
    input_model: type[Input],
    arguments: ToolArguments,
    execute: Callable[[Input], Mapping[str, Any]],
) -> str:
    try:
        parsed_arguments = input_model.model_validate({} if arguments is None else arguments)
    except ValidationError as error:
        context.report_error(f"tools.{tool_name}", error)
        return to_tool_json(serialize_invalid_arguments(error))
    return to_tool_json(execute(parsed_arguments))
