from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyIndexEntry:
    section_id: str
    title: str
    parent_title: str | None


@dataclass(frozen=True)
class PolicyExcerpt:
    section_id: str
    title: str
    parent_title: str | None
    text: str
    clarifications: tuple[str, ...]


@dataclass(frozen=True)
class PolicyLookup:
    sections: tuple[PolicyExcerpt, ...]
    unknown_section_ids: tuple[str, ...]


@dataclass(frozen=True)
class PolicySearchResult:
    sections: tuple[PolicyExcerpt, ...]
