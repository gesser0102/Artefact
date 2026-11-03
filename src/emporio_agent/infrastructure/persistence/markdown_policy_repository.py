import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emporio_agent.domain.exceptions import DataLoadError
from emporio_agent.domain.policies import PolicySection
from emporio_agent.infrastructure.observability.logging import log_error

POLICIES_FILE_NAME = "policies.md"
LOAD_SCOPE = "markdown_policy_repository.load"
DOCUMENT_TITLE_LEVEL = 1
SECTION_LEVEL = 2
SUBSECTION_LEVEL = 3
HEADING_PATTERN = re.compile(r"(#+)(?:[ \t]+(.*?))?[ \t]*")
SECTION_HEADING_PATTERN = re.compile(r"([0-9]+)\.?[ \t]+(\S.*)")
SUBSECTION_HEADING_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.?[ \t]+(\S.*)")


@dataclass(frozen=True)
class Heading:
    line_index: int
    level: int
    text: str

    @property
    def line_number(self) -> int:
        return self.line_index + 1


def headings_in(lines: Sequence[str]) -> list[Heading]:
    headings = []
    for line_index, line in enumerate(lines):
        match = HEADING_PATTERN.fullmatch(line)
        if match is not None:
            headings.append(Heading(line_index, len(match.group(1)), match.group(2) or ""))
    return headings


def first_section_position(headings: Sequence[Heading]) -> int:
    for position, heading in enumerate(headings):
        if heading.level == SECTION_LEVEL:
            return position
        if heading.level != DOCUMENT_TITLE_LEVEL:
            raise ValueError(f"line {heading.line_number}: heading before the first section")
    raise ValueError("no sections found")


def top_level_section(heading: Heading, body: str) -> PolicySection:
    match = SECTION_HEADING_PATTERN.fullmatch(heading.text)
    if match is None:
        raise ValueError(f"line {heading.line_number}: section heading without number")
    return PolicySection(
        section_id=match.group(1),
        title=match.group(2),
        parent_id=None,
        parent_title=None,
        body=body,
    )


def subsection(heading: Heading, parent: PolicySection, body: str) -> PolicySection:
    match = SUBSECTION_HEADING_PATTERN.fullmatch(heading.text)
    if match is None:
        raise ValueError(f"line {heading.line_number}: subsection heading without number")
    if match.group(1) != parent.section_id:
        raise ValueError(f"line {heading.line_number}: subsection outside its parent section")
    return PolicySection(
        section_id=f"{match.group(1)}.{match.group(2)}",
        title=match.group(3),
        parent_id=parent.section_id,
        parent_title=parent.title,
        body=body,
    )


def section_from(heading: Heading, parent: PolicySection | None, body: str) -> PolicySection:
    if heading.level == SECTION_LEVEL:
        return top_level_section(heading, body)
    if heading.level == SUBSECTION_LEVEL and parent is not None:
        return subsection(heading, parent, body)
    raise ValueError(f"line {heading.line_number}: unexpected heading level")


def require_unique_ids(sections: Sequence[PolicySection]) -> None:
    seen: set[str] = set()
    for section in sections:
        if section.section_id in seen:
            raise ValueError("duplicate section id")
        seen.add(section.section_id)


def parse_sections(text: str) -> tuple[PolicySection, ...]:
    if not text.strip():
        raise ValueError("file is empty")
    lines = text.splitlines()
    all_headings = headings_in(lines)
    section_headings = all_headings[first_section_position(all_headings) :]
    body_ends = [heading.line_index for heading in section_headings[1:]] + [len(lines)]
    sections: list[PolicySection] = []
    parent: PolicySection | None = None
    for heading, body_end in zip(section_headings, body_ends, strict=True):
        body = "\n".join(lines[heading.line_index + 1 : body_end]).strip()
        section = section_from(heading, parent, body)
        if section.is_top_level:
            parent = section
        sections.append(section)
    require_unique_ids(sections)
    return tuple(sections)


@dataclass(frozen=True)
class MarkdownPolicyRepository:
    sections: tuple[PolicySection, ...]

    @classmethod
    def load(cls, path: Path) -> Self:
        try:
            sections = parse_sections(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log_error(LOAD_SCOPE, error, file_name=path.name)
            raise DataLoadError("Could not load the policy manual") from error
        return cls(sections=sections)

    def list_sections(self) -> Sequence[PolicySection]:
        return self.sections
