import pytest

from emporio_agent.application.policies.dtos import PolicyExcerpt, PolicyIndexEntry
from emporio_agent.application.policies.service import (
    DEFAULT_POLICY_SEARCH_LIMIT,
    MAX_POLICY_SEARCH_LIMIT,
    MAX_UNKNOWN_SECTION_ID_LENGTH,
    PolicyService,
    normalized_section_id,
)
from emporio_agent.domain.policies import clarifications_for
from fakes import InMemoryPolicyRepository, make_section

ABOUT = make_section("1", "Sobre a Loja", "Loja de instrumentos.")
MISSION = make_section("1.1", "Missão", "Democratizar a música.", parent=ABOUT)
COMPANY = make_section("1.2", "Dados da Empresa", "CNPJ 00.000.000/0001-00", parent=ABOUT)
HOURS = make_section("2", "Horário de Funcionamento", "Segunda a sexta, 9h às 18h.")
SHIPPING = make_section("5", "Frete e Entregas")
LOCAL = make_section("5.1", "Entregas Locais", "Motoboy próprio.", parent=SHIPPING)
REMOTE = make_section("5.2", "Outras Cidades", "Correios e SEDEX.", parent=SHIPPING)
EMPTY_LEAF = make_section("6", "Seção Vazia")
SECTIONS = (ABOUT, MISSION, COMPANY, HOURS, SHIPPING, LOCAL, REMOTE, EMPTY_LEAF)
UNALIASED_SECTIONS = tuple(
    make_section(str(number), "Entregas", "entregas") for number in range(20, 28)
)


@pytest.fixture
def service() -> PolicyService:
    return PolicyService(InMemoryPolicyRepository(SECTIONS))


def ids_of(excerpts: tuple[PolicyExcerpt, ...]) -> list[str]:
    return [excerpt.section_id for excerpt in excerpts]


def test_search_limits_are_the_contract_values():
    assert DEFAULT_POLICY_SEARCH_LIMIT == 3
    assert MAX_POLICY_SEARCH_LIMIT == 5


def test_index_lists_sections_with_text_or_children_in_manual_order(service):
    assert service.index() == (
        PolicyIndexEntry("1", "Sobre a Loja", None),
        PolicyIndexEntry("1.1", "Missão", "Sobre a Loja"),
        PolicyIndexEntry("1.2", "Dados da Empresa", "Sobre a Loja"),
        PolicyIndexEntry("2", "Horário de Funcionamento", None),
        PolicyIndexEntry("5", "Frete e Entregas", None),
        PolicyIndexEntry("5.1", "Entregas Locais", "Frete e Entregas"),
        PolicyIndexEntry("5.2", "Outras Cidades", "Frete e Entregas"),
    )


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("4.2", "4.2"),
        (" 4.2 ", "4.2"),
        ("4.2.", "4.2"),
        ("4.", "4"),
        ("seção 4.2", "4.2"),
        ("Seção 4", "4"),
        ("secao 4.2", "4.2"),
        ("SEÇÃO   10", "10"),
        ("10", "10"),
    ],
)
def test_normalized_section_id_accepts_known_forms(reference, expected):
    assert normalized_section_id(reference) == expected


@pytest.mark.parametrize(
    "reference", ["", "abc", "4.2.1", "4,2", "seção", "capítulo 4", "4.2a", "-4", "4 .2"]
)
def test_normalized_section_id_rejects_other_forms(reference):
    assert normalized_section_id(reference) is None


def test_get_sections_returns_a_subsection_with_its_text(service):
    lookup = service.get_sections(["1.2"])

    assert lookup.sections == (
        PolicyExcerpt(
            section_id="1.2",
            title="Dados da Empresa",
            parent_title="Sobre a Loja",
            text="CNPJ 00.000.000/0001-00",
            clarifications=clarifications_for("1.2"),
        ),
    )
    assert lookup.unknown_section_ids == ()


def test_top_level_id_expands_to_itself_and_its_subsections(service):
    assert ids_of(service.get_sections(["seção 1"]).sections) == ["1", "1.1", "1.2"]


def test_top_level_without_text_expands_only_to_subsections(service):
    assert ids_of(service.get_sections(["5"]).sections) == ["5.1", "5.2"]


def test_expanded_excerpts_carry_their_own_clarifications(service):
    excerpts = service.get_sections(["1"]).sections

    assert [excerpt.clarifications for excerpt in excerpts] == [
        clarifications_for("1"),
        clarifications_for("1.1"),
        clarifications_for("1.2"),
    ]


def test_get_sections_deduplicates_preserving_first_order(service):
    lookup = service.get_sections(["1.2", "1", "1.2."])

    assert ids_of(lookup.sections) == ["1.2", "1", "1.1"]


def test_unknown_ids_are_collected_once_and_trimmed(service):
    long_reference = "x" * 100
    lookup = service.get_sections(["99", "  seção   99  ", "99", long_reference, "2"])

    assert ids_of(lookup.sections) == ["2"]
    assert lookup.unknown_section_ids == ("99", "seção 99", "x" * MAX_UNKNOWN_SECTION_ID_LENGTH)


def test_section_without_text_or_children_counts_as_unknown(service):
    lookup = service.get_sections(["6"])

    assert lookup.sections == ()
    assert lookup.unknown_section_ids == ("6",)


def test_search_returns_excerpts_with_clarifications(service):
    result = service.search("qual o cnpj")

    assert ids_of(result.sections) == ["1.2"]
    assert result.sections[0].clarifications == clarifications_for("1.2")


def test_search_never_returns_sections_without_text(service):
    assert "5" not in ids_of(service.search("frete e entregas", MAX_POLICY_SEARCH_LIMIT).sections)


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(-3, 1), (0, 1), (1, 1), (4, 4), (50, MAX_POLICY_SEARCH_LIMIT)],
)
def test_search_clamps_the_limit(limit, expected):
    service = PolicyService(InMemoryPolicyRepository(UNALIASED_SECTIONS))

    assert ids_of(service.search("entregas", limit).sections) == [
        section.section_id for section in UNALIASED_SECTIONS[:expected]
    ]


def test_search_uses_the_default_limit():
    service = PolicyService(InMemoryPolicyRepository(UNALIASED_SECTIONS))

    assert len(service.search("entregas").sections) == DEFAULT_POLICY_SEARCH_LIMIT


def test_search_without_matches_is_empty(service):
    assert service.search("receita de bolo").sections == ()


def test_empty_repository_yields_empty_results():
    service = PolicyService(InMemoryPolicyRepository())

    assert service.index() == ()
    assert service.search("frete").sections == ()
    assert service.get_sections(["1"]).unknown_section_ids == ("1",)
