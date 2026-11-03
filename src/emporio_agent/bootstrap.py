from dataclasses import dataclass

from emporio_agent.agent.tools.context import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.application.orders.service import OrderService
from emporio_agent.config import Settings
from emporio_agent.infrastructure.clock import SystemClock
from emporio_agent.infrastructure.observability.logging import configure_logging, log_error
from emporio_agent.infrastructure.persistence.csv_repository import CsvRepository


@dataclass(frozen=True)
class Container:
    repository: CsvRepository
    catalog_service: CatalogService
    order_service: OrderService
    tools: ToolContext


def build_container(settings: Settings) -> Container:
    configure_logging(settings.debug)
    repository = CsvRepository.load(settings.data_dir)
    catalog_service = CatalogService(repository)
    order_service = OrderService(repository, repository, SystemClock())
    return Container(
        repository=repository,
        catalog_service=catalog_service,
        order_service=order_service,
        tools=ToolContext(
            catalog=catalog_service,
            orders=order_service,
            report_error=log_error,
        ),
    )
