import pytest

from emporio_agent.domain.policies import STORE_CLARIFICATIONS_BY_SECTION, clarifications_for
from fakes import make_section

TOP_LEVEL = make_section("4", "Política de Trocas e Devoluções", "Texto")


def test_top_level_section_has_no_parent():
    assert TOP_LEVEL.is_top_level is True
    assert make_section("4.2", "Trocas por Defeito", parent=TOP_LEVEL).is_top_level is False


@pytest.mark.parametrize(("body", "expected"), [("Texto", True), ("", False)])
def test_has_body_reflects_text_presence(body, expected):
    assert make_section("5", "Frete", body).has_body is expected


def test_clarifications_for_known_section_keep_manual_order():
    assert clarifications_for("3.1") == (
        "Até 3x sem juros, a parcela mínima é de R$ 50,00.",
        "As regras desta seção prevalecem sobre a tabela da seção 3.",
    )


def test_clarifications_for_unknown_section_are_empty():
    assert clarifications_for("99") == ()


def test_official_contact_data_is_in_the_clarifications():
    assert "(67) 3341-4444" in clarifications_for("1.2")[0]
    assert "contato@emporiodamusica.com.br" in clarifications_for("1.2")[1]
    assert "(67) 3341-4444" in clarifications_for("7")[0]


def test_every_clarification_is_non_empty_text():
    assert all(
        notes and all(note.strip() for note in notes)
        for notes in STORE_CLARIFICATIONS_BY_SECTION.values()
    )
