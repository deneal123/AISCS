"""Deterministic citation existence and paragraph coverage audit."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .sources import SourceRegistry

_CITATION_RE = re.compile(r"\[(\d{1,4})\]")
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_CODE_FENCE_RE = re.compile(r"^\s*```")


@dataclass(frozen=True, slots=True)
class CitationAudit:
    valid: bool
    cited_ids: tuple[int, ...]
    invalid_ids: tuple[int, ...]
    key_paragraph_count: int
    covered_paragraph_count: int
    coverage_ratio: float
    sources_cited: int

    def bounded_metadata(self) -> dict[str, int | float | bool]:
        return {
            "valid": self.valid,
            "citation_count": len(self.cited_ids),
            "invalid_citation_count": len(self.invalid_ids),
            "key_paragraph_count": self.key_paragraph_count,
            "covered_paragraph_count": self.covered_paragraph_count,
            "coverage_ratio": round(self.coverage_ratio, 3),
            "sources_cited": self.sources_cited,
        }


def citation_ids(text: str) -> tuple[int, ...]:
    return tuple(int(value) for value in _CITATION_RE.findall(text or ""))


def _paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    in_code = False
    for line in str(text or "").splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if in_code:
            continue
        if not line.strip():
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if _HEADING_RE.match(line):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(line.strip())
    if current:
        paragraphs.append(" ".join(current).strip())
    return paragraphs


def _is_key_paragraph(paragraph: str) -> bool:
    text = paragraph.strip()
    if len(text) < 120:
        return False
    if _NUMBERED_LIST_RE.match(text) and len(text) < 220:
        return False
    # Recommendations and explicit uncertainty need not cite every sentence; factual
    # paragraphs with dates/numbers/comparisons still do.
    lower = text.casefold()
    recommendation = any(
        marker in lower
        for marker in (
            "рекомендуется",
            "следует рассмотреть",
            "практический шаг",
            "нужно учитывать",
        )
    )
    factual_signal = bool(re.search(r"\b\d+(?:[.,]\d+)?%?\b", text)) or any(
        marker in lower for marker in ("исследован", "данн", "по сравнению", "согласно", "показал")
    )
    return factual_signal or not recommendation


def audit_citations(
    report: str,
    registry: SourceRegistry,
    *,
    minimum_coverage: float = 0.75,
) -> CitationAudit:
    cited = citation_ids(report)
    known = registry.ids
    invalid = tuple(sorted(set(item for item in cited if item not in known)))
    paragraphs = [item for item in _paragraphs(report) if _is_key_paragraph(item)]
    covered = sum(1 for item in paragraphs if _CITATION_RE.search(item))
    ratio = covered / len(paragraphs) if paragraphs else (1.0 if cited else 0.0)
    cited_known = set(cited).intersection(known)
    valid = bool(known) and not invalid and bool(cited_known) and ratio >= minimum_coverage
    return CitationAudit(
        valid=valid,
        cited_ids=cited,
        invalid_ids=invalid,
        key_paragraph_count=len(paragraphs),
        covered_paragraph_count=covered,
        coverage_ratio=ratio,
        sources_cited=len(cited_known),
    )


def strip_invalid_citations(report: str, registry: SourceRegistry) -> str:
    known = registry.ids

    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) in known else ""

    return _CITATION_RE.sub(_replace, report)


__all__ = [
    "CitationAudit",
    "audit_citations",
    "citation_ids",
    "strip_invalid_citations",
]
