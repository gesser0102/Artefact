from collections.abc import Mapping
from typing import Any

from emporio_agent.agent.tools.context import ToolArguments, ToolContext, run_tool
from emporio_agent.agent.tools.schemas import GetPolicySectionsInput, SearchPoliciesInput
from emporio_agent.agent.tools.serialization import (
    serialize_policy_lookup,
    serialize_policy_search,
)

SEARCH_POLICIES = "search_policies"
GET_POLICY_SECTIONS = "get_policy_sections"


def search_policies(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(parsed: SearchPoliciesInput) -> Mapping[str, Any]:
        return serialize_policy_search(
            context.policies.search(parsed.query, parsed.limit),
            context.policies.index(),
        )

    return run_tool(context, SEARCH_POLICIES, SearchPoliciesInput, arguments, execute)


def get_policy_sections(context: ToolContext, arguments: ToolArguments = None) -> str:
    def execute(parsed: GetPolicySectionsInput) -> Mapping[str, Any]:
        return serialize_policy_lookup(
            context.policies.get_sections(parsed.section_ids),
            context.policies.index(),
        )

    return run_tool(context, GET_POLICY_SECTIONS, GetPolicySectionsInput, arguments, execute)
