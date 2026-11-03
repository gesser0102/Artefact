from dataclasses import dataclass

from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.application.policies.service import PolicyService
from emporio_agent.config import Settings
from emporio_agent.infrastructure.clock import SystemClock
from emporio_agent.infrastructure.observability.logging import configure_logging, log_error
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


def build_container(settings: Settings) -> Container:
    configure_logging(settings.debug)
    repository = CsvRepository.load(settings.data_dir)
    policy_repository = MarkdownPolicyRepository.load(settings.data_dir / POLICIES_FILE_NAME)
    catalog_service = CatalogService(repository)
    order_service = OrderService(repository, repository, SystemClock())
    policy_service = PolicyService(policy_repository)
    return Container(
        repository=repository,
        catalog_service=catalog_service,
        order_service=order_service,
        policy_service=policy_service,
        tools=ToolContext(
            catalog=catalog_service,
            orders=order_service,
            policies=policy_service,
            report_error=log_error,
        ),
    )
