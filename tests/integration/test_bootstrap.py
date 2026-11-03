import json
import logging
import shutil
from pathlib import Path

import pytest

from emporio_agent.agent.tools.catalog_tools import search_products
from emporio_agent.agent.tools.order_tools import get_order_status
from emporio_agent.agent.tools.policy_tools import get_policy_sections, search_policies
from emporio_agent.bootstrap import build_container
from emporio_agent.config import Settings
from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.infrastructure.observability.logging import LOGGER_NAME, log_error
from emporio_agent.infrastructure.persistence.markdown_policy_repository import (
    LOAD_SCOPE,
    POLICIES_FILE_NAME,
)

DATA_DIR_ENV_VAR = "EMPORIO_DATA_DIR"
DEBUG_ENV_VAR = "EMPORIO_DEBUG"


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(DEBUG_ENV_VAR, raising=False)

    settings = Settings()

    assert settings.data_dir == Path("data")
    assert settings.debug is False


def test_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(DEBUG_ENV_VAR, "1")

    settings = Settings()

    assert settings.data_dir == tmp_path
    assert settings.debug is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        (" TRUE ", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("talvez", False),
    ],
)
def test_debug_flag_keeps_previous_semantics(monkeypatch, raw, expected):
    monkeypatch.setenv(DEBUG_ENV_VAR, raw)

    assert Settings().debug is expected


def test_build_container_wires_tools_to_real_data(data_dir):
    container = build_container(Settings(data_dir=data_dir))

    assert json.loads(search_products(container.tools, {"query": "Takamine GD20"}))["returned"] == 1
    assert container.repository.get_customer(1) is not None
    assert container.repository.get_order(1) is not None
    assert container.repository.list_order_items(1)
    assert json.loads(get_order_status(container.tools)) == {"verified": False}
    assert container.tools.policies is container.policy_service


def test_build_container_wires_policy_tools_to_the_real_manual(data_dir):
    container = build_container(Settings(data_dir=data_dir))

    search = json.loads(search_policies(container.tools, {"query": "qual o cnpj"}))
    lookup = json.loads(get_policy_sections(container.tools, {"section_ids": ["4.2"]}))

    assert search["query_matched"] is True
    assert search["sections"][0]["section_id"] == "1.2"
    assert lookup["sections"][0]["title"] == "Trocas por Defeito"
    assert len(container.policy_service.index()) == 28


def test_build_container_requires_the_policy_manual(tmp_path, data_dir, caplog):
    for csv_path in data_dir.glob("*.csv"):
        shutil.copy(csv_path, tmp_path / csv_path.name)

    with pytest.raises(DataLoadError):
        build_container(Settings(data_dir=tmp_path))

    assert LOAD_SCOPE in caplog.text
    assert POLICIES_FILE_NAME in caplog.text


@pytest.mark.parametrize(("debug", "level"), [(True, logging.DEBUG), (False, logging.ERROR)])
def test_build_container_configures_logging_level(data_dir, debug, level):
    build_container(Settings(data_dir=data_dir, debug=debug))

    assert logging.getLogger(LOGGER_NAME).level == level


def test_log_error_does_not_configure_logging():
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.WARNING)
    root_handlers = list(logging.getLogger().handlers)

    log_error("scope", ValueError("sem efeito colateral"))

    assert logger.level == logging.WARNING
    assert logging.getLogger().handlers == root_handlers


def test_build_container_propagates_data_load_error(tmp_path):
    with pytest.raises(DataLoadError):
        build_container(Settings(data_dir=tmp_path / "missing"))


def test_invalid_tool_arguments_reach_log_error(tools, caplog):
    output = search_products(tools, {"max_price": "lucas@jmail.com"})

    assert json.loads(output)["error"] == "invalid_arguments"
    assert "tools.search_products" in caplog.text
    assert "lucas" not in caplog.text


def test_search_tool_accepts_the_maximum_limit(tools):
    result = json.loads(search_products(tools, {"include_unavailable": True, "limit": 20}))

    assert result["returned"] == 20
    assert result["total_matches"] == 65


def test_search_payload_stays_compact_for_every_category(tools):
    for category_id in range(1, 10):
        for include_unavailable in (False, True):
            payload = search_products(
                tools, {"category": category_id, "include_unavailable": include_unavailable}
            )

            assert len(payload) < 1500
