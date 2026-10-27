"""Private compiler/page context for repair, not a diagnosis of causality."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from service.domain.documents.semantic.draft import DocumentDraft

_BLOCK_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
PageBlocks = tuple[tuple[int, tuple[str, ...]], ...]
SOURCE_REPAIR_CODES = frozenset(
    {
        "missing_math_delimiter",
        "unbalanced_group",
        "invalid_command_argument",
        "undefined_control_sequence",
        "invalid_alignment",
        "invalid_dimension",
        "missing_file",
    }
)
_TARGETED_REPAIR_CODES = SOURCE_REPAIR_CODES | {
    "layout_overflow",  # Existing internal layout compatibility diagnostic.
    "visual_blank_page",
    "visual_clipping",
    "visual_overlap",
    "visual_readability",
    "visual_table_overflow",
    "visual_image_quality",
    "visual_header_footer",
    "visual_composition",
}


def repair_target_ids(diagnostics: list[str], draft: DocumentDraft) -> frozenset[str] | None:
    """No clipping, global fallback or partial admission of an unowned condition."""
    if not isinstance(diagnostics, list) or not 1 <= len(diagnostics) <= 20:
        return None
    known = {block.block_id for block in draft.blocks}
    targets: set[str] = set()
    for item in diagnostics:
        if not isinstance(item, str) or len(item) > 129 or item.count(":") != 1:
            return None
        code, block = item.split(":")
        if (
            code not in _TARGETED_REPAIR_CODES
            or not _BLOCK_ID.fullmatch(block)
            or block not in known
        ):
            return None
        targets.add(block)
    return frozenset(targets)


def scoped_source_diagnostics(
    status: dict[str, Any], draft: DocumentDraft | None
) -> tuple[str, ...] | None:
    """Repair content only when every fatal compiler condition has an owned scope."""
    raw = status.get("diagnostics")
    failure = status.get("failure_code")
    if (
        draft is None
        or status.get("state") != "failed"
        or not isinstance(failure, str)
        or failure not in {"compile_failed", "audit_failed"}
        or not isinstance(raw, list)
        or not 1 <= len(raw) <= 100
    ):
        return None
    result: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        severity = item.get("severity", "error")
        if not isinstance(severity, str):
            return None
        if severity in {"info", "warning"}:
            continue
        code, block = item.get("code"), item.get("block_id")
        if severity != "error" or not isinstance(code, str) or code not in SOURCE_REPAIR_CODES:
            return None
        if not isinstance(block, str):
            return None
        diagnostic = f"{code}:{block}"
        if diagnostic not in result:
            result.append(diagnostic)
    return tuple(result) if repair_target_ids(result, draft) is not None else None


def compiler_diagnostic_codes(status: dict[str, Any]) -> list[str]:
    return [
        (f"{str(item.get('code') or 'compile_failed')}:{str(item.get('block_id') or '')}").rstrip(
            ":"
        )
        for item in status.get("diagnostics", [])
        if isinstance(item, dict)
    ] or [str(status.get("failure_code") or "compile_failed")]


def page_provenance(raw: Any, page_count: int) -> PageBlocks:
    if not isinstance(raw, list) or len(raw) > 200:
        return ()
    pages: dict[int, tuple[str, ...]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            return ()
        page, blocks = entry.get("page"), entry.get("block_ids")
        if (
            type(page) is not int
            or not 1 <= page <= page_count
            or page in pages
            or not isinstance(blocks, list)
            or not 1 <= len(blocks) <= 120
            or any(not isinstance(block, str) or not _BLOCK_ID.fullmatch(block) for block in blocks)
            or len(set(blocks)) != len(blocks)
        ):
            return ()
        pages[page] = tuple(blocks)
    return tuple(sorted(pages.items()))


def scoped_visual_diagnostics(
    diagnostics: Iterable[dict[str, Any]],
    pages: PageBlocks,
    draft: DocumentDraft | None,
    allowed_codes: frozenset[str],
) -> tuple[str, ...] | None:
    if draft is None:
        return None
    known = {block.block_id for block in draft.blocks}
    mapping = dict(pages)
    result: list[str] = []
    for issue in diagnostics:
        if not isinstance(issue, dict):
            return None
        code, page = issue.get("code"), issue.get("page")
        if not isinstance(code, str) or code not in allowed_codes or type(page) is not int:
            return None
        candidates = mapping.get(page, ())
        if not candidates or not set(candidates).issubset(known):
            return None
        for block in candidates:
            diagnostic = f"{code}:{block}"
            if diagnostic not in result:
                result.append(diagnostic)
        if len(result) > 20:
            return None
    return tuple(result) if result else None
