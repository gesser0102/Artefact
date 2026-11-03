from pathlib import Path

import pytest

from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.policies import STORE_CLARIFICATIONS_BY_SECTION
from emporio_agent.infrastructure.persistence.markdown_policy_repository import (
    LOAD_SCOPE,
    POLICIES_FILE_NAME,
    MarkdownPolicyRepository,
)

MANUAL_SECTION_IDS = [
    "1",
    "1.1",
    "1.2",
    "2",
    "3",
    "3.1",
    "4",
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    "5",
    "5.1",
    "5.2",
    "5.3",
    "6",
    "6.1",
    "6.2",
    "7",
    "7.1",
    "7.2",
    "7.3",
    "8",
    "8.1",
    "8.2",
    "8.3",
    "9",
    "10",
]
SECTIONS_WITHOUT_BODY = {"5", "6", "8"}
SECRET_MARKER = "conteudo-sigiloso-do-manual"
VALID_MANUAL = """# MANUAL

Capa ignorada.

## 1. Primeira Seção

Texto da primeira.

### 1.1 Subseção

Texto da subseção.

## 2 Segunda Sem Ponto

Texto da segunda.
"""


@pytest.fixture(scope="module")
def manual(data_dir) -> MarkdownPolicyRepository:
    return MarkdownPolicyRepository.load(data_dir / POLICIES_FILE_NAME)


def by_id(repository: MarkdownPolicyRepository) -> dict[str, object]:
    return {section.section_id: section for section in repository.list_sections()}


def write_manual(tmp_path: Path, content: str) -> Path:
    path = tmp_path / POLICIES_FILE_NAME
    path.write_text(content, encoding="utf-8")
    return path


def test_real_manual_has_every_section_in_order(manual):
    assert [section.section_id for section in manual.list_sections()] == MANUAL_SECTION_IDS


def test_real_manual_bodies_are_filled_where_the_manual_has_text(manual):
    empty_ids = {section.section_id for section in manual.list_sections() if not section.body}

    assert empty_ids == SECTIONS_WITHOUT_BODY


def test_real_manual_titles_and_parents(manual):
    sections = by_id(manual)

    assert sections["2"].title == "Horário de Funcionamento"
    assert sections["2"].parent_id is None
    assert sections["2"].parent_title is None
    assert sections["4.2"].title == "Trocas por Defeito"
    assert sections["4.2"].parent_id == "4"
    assert sections["4.2"].parent_title == "Política de Trocas e Devoluções"
    assert sections["10"].title == "Disposições Finais"


def test_real_manual_bodies_stop_at_the_next_heading(manual):
    sections = by_id(manual)

    assert sections["3"].body.startswith("Aceitamos as seguintes formas de pagamento")
    assert "Parcelamento de 4x a 6x" not in sections["3"].body
    assert "Parcelamento de 4x a 6x" in sections["3.1"].body
    assert sections["5.2"].body.endswith("entrar em contato imediatamente com a loja.")


def test_real_manual_ignores_the_cover(manual):
    assert all("Versão 2.1 — Junho de 2025\n" not in s.body for s in manual.list_sections())
    assert "MANUAL DE POLÍTICAS" not in by_id(manual)["1"].body


def test_every_clarification_key_is_a_real_manual_section(manual):
    assert set(STORE_CLARIFICATIONS_BY_SECTION) <= set(by_id(manual))


def test_valid_manual_variants_parse(tmp_path):
    repository = MarkdownPolicyRepository.load(write_manual(tmp_path, VALID_MANUAL))

    assert [(s.section_id, s.title, s.body) for s in repository.list_sections()] == [
        ("1", "Primeira Seção", "Texto da primeira."),
        ("1.1", "Subseção", "Texto da subseção."),
        ("2", "Segunda Sem Ponto", "Texto da segunda."),
    ]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   \n\n",
        "# Só a capa\n\nTexto sem seções.\n",
        f"## Sem número\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n### Sem número\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n### 2.1 Pai errado\n\n{SECRET_MARKER}\n",
        f"### 1.1 Antes da primeira seção\n\n## 1. Ok\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n## 1. Repetida\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n### 1.1 A\n\n### 1.1 B\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n# Título no meio\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n#### 1.1.1 Profunda\n\n{SECRET_MARKER}\n",
        f"## 1. Ok\n\n##\n\n{SECRET_MARKER}\n",
        f"## 4.2 Subseção como seção\n\n{SECRET_MARKER}\n",
    ],
)
def test_malformed_manual_raises_and_logs_without_content(tmp_path, caplog, content):
    path = write_manual(tmp_path, content)

    with pytest.raises(DataLoadError):
        MarkdownPolicyRepository.load(path)

    assert LOAD_SCOPE in caplog.text
    assert SECRET_MARKER not in caplog.text
    assert "Pai errado" not in caplog.text


def test_missing_manual_raises_data_load_error(tmp_path, caplog):
    with pytest.raises(DataLoadError):
        MarkdownPolicyRepository.load(tmp_path / POLICIES_FILE_NAME)

    assert LOAD_SCOPE in caplog.text
    assert POLICIES_FILE_NAME in caplog.text


def test_non_utf8_manual_raises_data_load_error(tmp_path, caplog):
    path = tmp_path / POLICIES_FILE_NAME
    path.write_bytes("## 1. Política\n\nCartão de crédito\n".encode("latin-1"))

    with pytest.raises(DataLoadError):
        MarkdownPolicyRepository.load(path)

    assert LOAD_SCOPE in caplog.text
    assert "Cart" not in caplog.text
