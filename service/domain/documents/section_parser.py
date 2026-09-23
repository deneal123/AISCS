"""Trusted normalization for one model-authored semantic document section."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from .draft import DraftBlock, parse_block
from .evidence import CitationRegistry
from .outline import DocumentOutlineSection, section_role

AuthoringFailureCode = Literal["draft_protocol", "draft_invalid", "citation_unknown"]
AuthoringRejectionReason = Literal[
    "response_missing",
    "blocks_invalid",
    "block_kind_unsupported",
    "section_scope_violation",
    "block_invalid",
    "citation_unknown",
]
_CITATION_KIND = "citation"
_SECTION_KIND = "section"

_DOCUMENT_BLOCK_KINDS: dict[str, frozenset[str]] = {
    "presentation": frozenset({"slide"}),
    "article": frozenset(
        {"section", "paragraph", "list", "table", "figure", "equation", "callout", "citation"}
    ),
    "report": frozenset(
        {"section", "paragraph", "list", "table", "figure", "equation", "callout", "citation"}
    ),
    "legal": frozenset({"section", "paragraph", "list", "table", "callout", "signature"}),
    "generic": frozenset(
        {
            "section",
            "paragraph",
            "list",
            "table",
            "figure",
            "equation",
            "callout",
            "signature",
            "citation",
        }
    ),
}


def _stable_block_id(
    raw: dict[str, Any],
    ordinal: int,
    seen: set[str],
    *,
    section_id: str,
) -> str:
    kind = str(raw.get("kind") or "block")[:16].lower()
    seed = "\x1f".join(
        (
            section_id,
            kind,
            str(raw.get("title") or "")[:300],
            str(raw.get("text") or "")[:1_000],
        )
    )
    suffix = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:10]
    stem = "".join(character if character.isalnum() else "_" for character in kind)
    candidate = f"{stem or 'block'}_{ordinal:03d}_{suffix}"[:64]
    while candidate in seen:
        ordinal += 1
        candidate = f"{stem or 'block'}_{ordinal:03d}_{suffix}"[:64]
    seen.add(candidate)
    return candidate


def _citation_block(
    source_id: Any,
    *,
    ordinal: int,
    seen: set[str],
    section_id: str,
) -> DraftBlock | None:
    raw = {
        "kind": _CITATION_KIND,
        "title": "",
        "text": "",
        "items": [],
        "columns": [],
        "rows": [],
        "source_id": source_id,
        "asset_path": "",
        "level": 1,
    }
    return parse_block(
        {
            **raw,
            "block_id": _stable_block_id(raw, ordinal, seen, section_id=section_id),
        }
    )


def _ensure_heading(
    blocks: list[DraftBlock],
    section: DocumentOutlineSection,
    *,
    seen: set[str],
    document_kind: str,
) -> bool:
    if document_kind == "presentation" or any(
        item.kind == "section" and item.title.strip().casefold() == section.title.casefold()
        for item in blocks
    ):
        return True
    abstract_index = (
        next((index for index, item in enumerate(blocks) if item.kind == "paragraph"), None)
        if document_kind == "article" and section_role(section.title) == "abstract"
        else None
    )
    abstract_text = blocks[abstract_index].text if abstract_index is not None else ""
    if abstract_index is not None:
        blocks.pop(abstract_index)
    raw = {"kind": _SECTION_KIND, "title": section.title, "text": abstract_text}
    heading = parse_block(
        {
            **raw,
            "block_id": _stable_block_id(raw, 0, seen, section_id=section.section_id),
        }
    )
    if heading is None:
        return False
    blocks.insert(0, heading)
    return True


def parse_authored_section(
    raw: dict[str, Any] | None,
    section: DocumentOutlineSection,
    citations: CitationRegistry | None,
    *,
    document_kind: str,
) -> tuple[
    tuple[DraftBlock, ...] | None,
    AuthoringFailureCode | None,
    AuthoringRejectionReason | None,
]:
    if not isinstance(raw, dict):
        return None, "draft_protocol", "response_missing"
    raw_blocks = raw.get("blocks")
    if not isinstance(raw_blocks, list) or not 1 <= len(raw_blocks) <= 24:
        return None, "draft_invalid", "blocks_invalid"
    permitted_kinds = _DOCUMENT_BLOCK_KINDS.get(document_kind, frozenset())
    seen: set[str] = set()
    normalized: list[DraftBlock] = []
    for ordinal, raw_block in enumerate(raw_blocks, start=1):
        if (
            not isinstance(raw_block, dict)
            or str(raw_block.get("kind") or "") not in permitted_kinds
        ):
            return None, "draft_invalid", "block_kind_unsupported"
        if raw_block.get("kind") == "section":
            return None, "draft_invalid", "section_scope_violation"
        source_id = raw_block.get("source_id")
        needs_citation = (
            source_id is not None
            and source_id != 0
            and raw_block.get("kind") not in {"citation", "slide"}
        )
        block = parse_block(
            {
                **raw_block,
                **({"source_id": 0} if needs_citation else {}),
                "block_id": _stable_block_id(
                    raw_block,
                    ordinal,
                    seen,
                    section_id=section.section_id,
                ),
            }
        )
        if block is None:
            return None, "draft_invalid", "block_invalid"
        normalized.append(block)
        if needs_citation:
            citation = _citation_block(
                source_id,
                ordinal=ordinal,
                seen=seen,
                section_id=section.section_id,
            )
            if citation is None:
                return None, "draft_invalid", "block_invalid"
            normalized.append(citation)
    if not _ensure_heading(
        normalized,
        section,
        seen=seen,
        document_kind=document_kind,
    ):
        return None, "draft_invalid", "block_invalid"
    cited = frozenset(block.source_id for block in normalized if block.source_id is not None)
    if citations is None and cited:
        return None, "citation_unknown", "citation_unknown"
    if citations is not None and not cited.issubset(citations.artifact.source_ids):
        return None, "citation_unknown", "citation_unknown"
    return tuple(normalized), None, None


__all__ = [
    "AuthoringFailureCode",
    "AuthoringRejectionReason",
    "parse_authored_section",
]
