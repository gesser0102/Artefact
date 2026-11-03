from dataclasses import dataclass

from emporio_agent.agent.conversation import ConversationAgent
from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.config import Settings
from emporio_agent.infrastructure.clock import SystemClock
from emporio_agent.infrastructure.llm.groq_chat_model import GroqChatModel
from emporio_agent.infrastructure.observability.logging import (
    configure_logging,
    log_error,
    log_warning,
)
from emporio_agent.infrastructure.observability.trace_sink import JsonlTraceSink
from emporio_agent.infrastructure.persistence.csv_repository import CsvRepository
from emporio_agent.infrastructure.persistence.markdown_policy_repository import (
    POLICIES_FILE_NAME,
    MarkdownPolicyRepository,
)


@dataclass(frozen=True)
class Container:
    repository: CsvRepository
    catalog_service: CatalogService
    order_service: OrderService
    policy_service: PolicyService
    tools: ToolContext
    agent: ConversationAgent | None


def build_chat_model(settings: Settings) -> GroqChatModel | None:
    if settings.groq_api_key is None:
        return None
    return GroqChatModel(
        base_url=settings.llm_base_url,
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.model,
        fallback_model=settings.fallback_model,
        timeout=settings.llm_timeout_seconds,
        max_completion_tokens=settings.max_completion_tokens,
        reasoning_effort=settings.reasoning_effort,
        temperature=settings.temperature,
    )


def build_agent(
    settings: Settings,
    tools: ToolContext,
    clock: SystemClock,
    policy_service: PolicyService,
) -> ConversationAgent | None:
    chat_model = build_chat_model(settings)
    if chat_model is None:
        return None
    return ConversationAgent(
        model=chat_model,
        tools=tools,
        clock=clock,
        policy_index=policy_service.index,
        trace_sink=None if settings.trace_dir is None else JsonlTraceSink(settings.trace_dir),
    )


def build_container(settings: Settings) -> Container:
    configure_logging(settings.debug)
    repository = CsvRepository.load(settings.data_dir)
    policy_repository = MarkdownPolicyRepository.load(settings.data_dir / POLICIES_FILE_NAME)
    clock = SystemClock()
    catalog_service = CatalogService(repository)
    order_service = OrderService(repository, repository, clock)
    policy_service = PolicyService(policy_repository)
    tools = ToolContext(
        catalog=catalog_service,
        orders=order_service,
        policies=policy_service,
        report_error=log_error,
        report_rejected_input=log_warning,
    )
    return Container(
        repository=repository,
        catalog_service=catalog_service,
        order_service=order_service,
        policy_service=policy_service,
        tools=tools,
        agent=build_agent(settings, tools, clock, policy_service),
    )
