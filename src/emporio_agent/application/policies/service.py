import re
from collections.abc import Sequence

from emporio_agent.application.policies.dtos import (
    PolicyExcerpt,
    PolicyIndexEntry,
    PolicyLookup,
    PolicySearchResult,
)
from emporio_agent.application.policies.search import rank_sections
from emporio_agent.application.ports import PolicyRepository
from emporio_agent.application.text import fold_text
from emporio_agent.domain.policies import PolicySection, clarifications_for

DEFAULT_POLICY_SEARCH_LIMIT = 3
MAX_POLICY_SEARCH_LIMIT = 5
MAX_UNKNOWN_SECTION_ID_LENGTH = 40
SECTION_REFERENCE_PATTERN = re.compile(r"(?:secao\s+)?([0-9]+(?:\.[0-9]+)?)\.?")


def normalized_section_id(reference: str) -> str | None:
    match = SECTION_REFERENCE_PATTERN.fullmatch(fold_text(reference).strip())
    return None if match is None else match.group(1)


def unknown_reference_text(reference: str) -> str:
    return " ".join(reference.split())[:MAX_UNKNOWN_SECTION_ID_LENGTH]


def excerpt_of(section: PolicySection) -> PolicyExcerpt:
    return PolicyExcerpt(
        section_id=section.section_id,
        title=section.title,
        parent_title=section.parent_title,
        text=section.body,
        clarifications=clarifications_for(section.section_id),
    )


def clamped_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_POLICY_SEARCH_LIMIT)


class PolicyService:
    def __init__(self, repository: PolicyRepository) -> None:
        self._repository = repository

    def index(self) -> tuple[PolicyIndexEntry, ...]:
        sections = self._repository.list_sections()
        parent_ids = {section.parent_id for section in sections}
        return tuple(
            PolicyIndexEntry(
                section_id=section.section_id,
                title=section.title,
                parent_title=section.parent_title,
            )
            for section in sections
            if section.has_body or section.section_id in parent_ids
        )

    def get_sections(self, section_ids: Sequence[str]) -> PolicyLookup:
        selected: dict[str, PolicyExcerpt] = {}
        unknown: dict[str, None] = {}
        for reference in section_ids:
            excerpts = self._excerpts_for(normalized_section_id(reference))
            if not excerpts:
                unknown[unknown_reference_text(reference)] = None
            for excerpt in excerpts:
                selected.setdefault(excerpt.section_id, excerpt)
        return PolicyLookup(sections=tuple(selected.values()), unknown_section_ids=tuple(unknown))

    def search(self, query: str, limit: int = DEFAULT_POLICY_SEARCH_LIMIT) -> PolicySearchResult:
        ranked = rank_sections(query, self._repository.list_sections(), clamped_limit(limit))
        return PolicySearchResult(sections=tuple(excerpt_of(section) for section in ranked))

    def _excerpts_for(self, section_id: str | None) -> tuple[PolicyExcerpt, ...]:
        if section_id is None:
            return ()
        sections = self._repository.list_sections()
        requested = [section for section in sections if section.section_id == section_id]
        if not requested:
            return ()
        children = [section for section in sections if section.parent_id == section_id]
        return tuple(excerpt_of(section) for section in [*requested, *children] if section.has_body)
