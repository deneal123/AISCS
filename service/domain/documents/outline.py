"""Bounded semantic outline used before section-by-section document authoring."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

from .draft import BlockKind

MAX_OUTLINE_SECTIONS = 16
OutlineRejectionReason = Literal[
    "response_missing",
    "outline_title_invalid",
    "outline_sections_invalid",
    "outline_section_invalid",
    "outline_block_kinds_invalid",
    "outline_source_ids_invalid",
]
_SUPPORTED_KINDS = frozenset(
    {
        "section",
        "paragraph",
        "list",
        "table",
        "figure",
        "equation",
        "callout",
        "slide",
        "signature",
        "citation",
    }
)
_ROLE_ALIASES = {
    "abstract": "abstract",
    "аннотация": "abstract",
    "introduction": "introduction",
    "введение": "introduction",
    "background": "background",
    "related work": "background",
    "обзор литературы": "background",
    "method": "method",
    "methods": "method",
    "methodology": "method",
    "метод": "method",
    "методы": "method",
    "методология": "method",
    "results": "results",
    "findings": "results",
    "результаты": "results",
    "discussion": "discussion",
    "обсуждение": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "заключение": "conclusion",
    "выводы": "conclusion",
    "references": "references",
    "bibliography": "references",
    "литература": "references",
    "список литературы": "references",
}
_ROLE_ORDER = {
    "abstract": 0,
    "introduction": 10,
    "background": 20,
    "method": 30,
    "results": 40,
    "discussion": 50,
    "conclusion": 80,
    "references": 90,
}
_GENERIC_TITLES = frozenset({"article", "body", "document", "title", "статья", "текст"})


def _title_key(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def section_role(value: str) -> str | None:
    return _ROLE_ALIASES.get(_title_key(value))


def _clean(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _section_id(title: str, ordinal: int) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:24] or "section"
    digest = hashlib.sha256(f"{ordinal}\x1f{title}".encode()).hexdigest()[:10]
    return f"{stem}_{ordinal:02d}_{digest}"[:64]


@dataclass(frozen=True, slots=True)
class DocumentOutlineSection:
    section_id: str
    title: str
    purpose: str
    block_kinds: tuple[BlockKind, ...]
    source_ids: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "purpose": self.purpose,
            "block_kinds": list(self.block_kinds),
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class DocumentOutline:
    title: str
    sections: tuple[DocumentOutlineSection, ...]

    def payload(self) -> dict[str, object]:
        return {"title": self.title, "sections": [item.payload() for item in self.sections]}


def ensure_required_outline_sections(
    outline: DocumentOutline,
    required_sections: tuple[str, ...],
) -> DocumentOutline:
    """Reserve outline capacity for every profile-owned section."""

    original: list[DocumentOutlineSection] = []
    seen_titles: set[str] = set()
    seen_roles: set[str] = set()
    for item in outline.sections:
        title_key = _title_key(item.title)
        role = section_role(item.title)
        if not title_key or title_key in _GENERIC_TITLES:
            continue
        if title_key in seen_titles or (role is not None and role in seen_roles):
            continue
        seen_titles.add(title_key)
        if role is not None:
            seen_roles.add(role)
        original.append(item)
    required_titles = tuple(
        dict.fromkeys(
            title for value in required_sections for title in [_clean(value, 300)] if title
        )
    )[:MAX_OUTLINE_SECTIONS]
    required_entries: list[tuple[DocumentOutlineSection, bool]] = []
    used: set[int] = set()
    for title in required_titles:
        title_key = _title_key(title)
        role = section_role(title)
        match_index = next(
            (
                index
                for index, item in enumerate(original)
                if index not in used
                and (
                    _title_key(item.title) == title_key
                    or (role and section_role(item.title) == role)
                )
            ),
            None,
        )
        if match_index is None:
            item = DocumentOutlineSection(
                section_id="",
                title=title,
                purpose=f"Cover the required profile section: {title}"[:2_000],
                block_kinds=("paragraph",),
                source_ids=(),
            )
        else:
            used.add(match_index)
            matched = original[match_index]
            item = DocumentOutlineSection(
                section_id="",
                title=title,
                purpose=matched.purpose,
                block_kinds=matched.block_kinds,
                source_ids=matched.source_ids,
            )
        required_entries.append((item, True))
    optional_entries = [(item, False) for index, item in enumerate(original) if index not in used]
    optional_entries = optional_entries[: max(0, MAX_OUTLINE_SECTIONS - len(required_entries))]
    entries = [*required_entries, *optional_entries]
    entries.sort(
        key=lambda entry: (
            _ROLE_ORDER.get(section_role(entry[0].title) or "", 60),
            _title_key(entry[0].title),
        )
    )
    sections = tuple(
        DocumentOutlineSection(
            section_id=_section_id(item.title, ordinal),
            title=item.title,
            purpose=item.purpose,
            block_kinds=item.block_kinds,
            source_ids=item.source_ids,
        )
        for ordinal, (item, _required) in enumerate(entries, start=1)
    )
    return DocumentOutline(outline.title, sections)


def parse_document_outline_result(
    value: Any,
    *,
    allowed_source_ids: frozenset[str],
) -> tuple[DocumentOutline | None, OutlineRejectionReason | None]:
    if not isinstance(value, dict):
        return None, "response_missing"
    title = _clean(value.get("title"), 300)
    raw_sections = value.get("sections")
    if not title:
        return None, "outline_title_invalid"
    if not isinstance(raw_sections, list):
        return None, "outline_sections_invalid"
    if not 1 <= len(raw_sections) <= MAX_OUTLINE_SECTIONS:
        return None, "outline_sections_invalid"
    sections: list[DocumentOutlineSection] = []
    for ordinal, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict):
            return None, "outline_section_invalid"
        section_title = _clean(raw.get("title"), 300)
        purpose = _clean(raw.get("purpose"), 2_000)
        raw_kinds = raw.get("block_kinds")
        raw_sources = raw.get("source_ids")
        if not section_title or not purpose or not isinstance(raw_kinds, list):
            return None, "outline_section_invalid"
        kinds = tuple(
            _clean(item, 24) for item in raw_kinds[:12] if _clean(item, 24) in _SUPPORTED_KINDS
        )
        if not kinds or len(kinds) != len(raw_kinds[:12]):
            return None, "outline_block_kinds_invalid"
        if not isinstance(raw_sources, list):
            return None, "outline_source_ids_invalid"
        # Outline references are advisory planning hints. Bind them to the
        # private run registry here and discard invented identifiers;
        # executable citation blocks remain strict in ``section_parser``.
        source_ids = tuple(
            dict.fromkeys(
                cleaned
                for item in raw_sources[:64]
                for cleaned in [_clean(item, 80)]
                if cleaned in allowed_source_ids
            )
        )
        sections.append(
            DocumentOutlineSection(
                section_id=_section_id(section_title, ordinal),
                title=section_title,
                purpose=purpose,
                block_kinds=kinds,  # type: ignore[arg-type]
                source_ids=source_ids,
            )
        )
    return DocumentOutline(title=title, sections=tuple(sections)), None


def parse_document_outline(
    value: Any,
    *,
    allowed_source_ids: frozenset[str],
) -> DocumentOutline | None:
    """Compatibility projection for existing checkpoint readers."""

    outline, _reason = parse_document_outline_result(
        value,
        allowed_source_ids=allowed_source_ids,
    )
    return outline


__all__ = [
    "DocumentOutline",
    "DocumentOutlineSection",
    "MAX_OUTLINE_SECTIONS",
    "OutlineRejectionReason",
    "ensure_required_outline_sections",
    "parse_document_outline",
    "parse_document_outline_result",
    "section_role",
]
