import logging
from pathlib import Path

import pytest

from emporio_agent.bootstrap import Container, build_container
from emporio_agent.config import Settings
from emporio_agent.infrastructure.observability.logging import LOGGER_NAME

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(autouse=True)
def restore_logger_level():
    logger = logging.getLogger(LOGGER_NAME)
    level = logger.level
    yield
    logger.setLevel(level)


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def container(data_dir) -> Container:
    return build_container(Settings(data_dir=data_dir, debug=False))


@pytest.fixture(scope="session")
def repository(container):
    return container.repository


@pytest.fixture(scope="session")
def service(container):
    return container.catalog_service


@pytest.fixture(scope="session")
def tools(container):
    return container.tools
