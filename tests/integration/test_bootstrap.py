import json
import logging
import shutil
from pathlib import Path

import pytest

from emporio_agent.agent.conversation import ConversationAgent
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
GROQ_KEY_ENV_VAR = "GROQ_API_KEY"
FAKE_KEY = "gsk_chave_de_teste_inexistente"


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(DEBUG_ENV_VAR, raising=False)

    settings = Settings(_env_file=None)

    assert settings.data_dir == Path("data")
    assert settings.debug is False


def test_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(DEBUG_ENV_VAR, "1")

    settings = Settings(_env_file=None)

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

    assert Settings(_env_file=None).debug is expected


def test_build_container_wires_tools_to_real_data(data_dir):
    container = build_container(Settings(_env_file=None, data_dir=data_dir))

    assert json.loads(search_products(container.tools, {"query": "Takamine GD20"}))["returned"] == 1
    assert container.repository.get_customer(1) is not None
    assert container.repository.get_order(1) is not None
    assert container.repository.list_order_items(1)
    assert json.loads(get_order_status(container.tools)) == {"verified": False}
    assert container.tools.policies is container.policy_service
    assert container.clock.now().utcoffset() is not None


def test_build_container_wires_policy_tools_to_the_real_manual(data_dir):
    container = build_container(Settings(_env_file=None, data_dir=data_dir))

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
        build_container(Settings(_env_file=None, data_dir=tmp_path))

    assert LOAD_SCOPE in caplog.text
    assert POLICIES_FILE_NAME in caplog.text


@pytest.mark.parametrize(("debug", "level"), [(True, logging.DEBUG), (False, logging.ERROR)])
def test_build_container_configures_logging_level(data_dir, debug, level):
    build_container(Settings(_env_file=None, data_dir=data_dir, debug=debug))

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
        build_container(Settings(_env_file=None, data_dir=tmp_path / "missing"))


def test_invalid_tool_arguments_reach_log_warning(tools, caplog):
    logging.getLogger(LOGGER_NAME).setLevel(logging.WARNING)

    output = search_products(tools, {"max_price": "lucas@jmail.com"})

    assert json.loads(output)["error"] == "invalid_arguments"
    assert "tools.search_products" in caplog.text
    assert "lucas" not in caplog.text
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_rejected_tool_input_is_silent_at_the_default_level(data_dir, caplog):
    container = build_container(Settings(_env_file=None, data_dir=data_dir))

    search_products(container.tools, {"max_price": "abc"})

    assert not caplog.records


def test_settings_read_the_groq_key_and_llm_options_from_an_env_file(monkeypatch, tmp_path):
    for name in (GROQ_KEY_ENV_VAR, f"EMPORIO_{GROQ_KEY_ENV_VAR}", "EMPORIO_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{GROQ_KEY_ENV_VAR}={FAKE_KEY}\nEMPORIO_MODEL=modelo-teste\nOUTRA_COISA=1\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == FAKE_KEY
    assert settings.model == "modelo-teste"
    assert FAKE_KEY not in repr(settings)


def test_settings_accept_the_prefixed_key_and_ignore_blank_values(monkeypatch):
    monkeypatch.delenv(GROQ_KEY_ENV_VAR, raising=False)
    monkeypatch.setenv(f"EMPORIO_{GROQ_KEY_ENV_VAR}", FAKE_KEY)

    assert Settings(_env_file=None).groq_api_key.get_secret_value() == FAKE_KEY

    monkeypatch.setenv(f"EMPORIO_{GROQ_KEY_ENV_VAR}", "   ")

    assert Settings(_env_file=None).groq_api_key is None


def test_settings_llm_defaults(monkeypatch):
    monkeypatch.delenv(GROQ_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(f"EMPORIO_{GROQ_KEY_ENV_VAR}", raising=False)

    settings = Settings(_env_file=None)

    assert settings.groq_api_key is None
    assert settings.model == "openai/gpt-oss-120b"
    assert settings.fallback_model is None
    assert settings.llm_base_url == "https://api.groq.com/openai/v1"
    assert settings.max_completion_tokens == 1024
    assert settings.reasoning_effort == "low"
    assert settings.trace_dir is None


def test_build_container_has_no_agent_without_a_key(monkeypatch, data_dir):
    monkeypatch.delenv(GROQ_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(f"EMPORIO_{GROQ_KEY_ENV_VAR}", raising=False)

    assert build_container(Settings(_env_file=None, data_dir=data_dir)).agent is None


def test_build_container_wires_the_agent_when_a_key_is_set(data_dir, tmp_path):
    settings = Settings(
        _env_file=None, data_dir=data_dir, groq_api_key=FAKE_KEY, trace_dir=tmp_path
    )

    agent = build_container(settings).agent

    assert isinstance(agent, ConversationAgent)
    assert agent.start_session().session_id


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
