from dataclasses import dataclass

from emporio_agent.agent.tools.catalog_tools import ToolContext
from emporio_agent.application.catalog.service import CatalogService
from emporio_agent.config import Settings
from emporio_agent.infrastructure.observability.logging import configure_logging, log_error
from emporio_agent.infrastructure.persistence.csv_repository import CsvCatalogRepository


@dataclass(frozen=True)
class Container:
    repository: CsvCatalogRepository
    catalog_service: CatalogService
    tools: ToolContext


def build_container(settings: Settings) -> Container:
    configure_logging(settings.debug)
    repository = CsvCatalogRepository.load(settings.data_dir)
    catalog_service = CatalogService(repository)
    return Container(
        repository=repository,
        catalog_service=catalog_service,
        tools=ToolContext(catalog=catalog_service, report_error=log_error),
    )
