"""Semantic authoring graph independent from LaTeX syntax."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Literal

BlockKind = Literal[
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
]

DRAFT_SCHEMA_VERSION = 1
_BLOCK_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_ASSET_PATH = re.compile(
    r"^figures/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:pdf|png|jpe?g|eps)$",
    re.IGNORECASE,
)
_KINDS = frozenset(
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


@dataclass(frozen=True, slots=True)
class DraftBlock:
    block_id: str
    kind: BlockKind
    title: str = ""
    text: str = ""
    items: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    source_id: int | None = None
    asset_path: str = ""
    level: int = 1


@dataclass(frozen=True, slots=True)
class DocumentDraft:
    schema_version: int
    version: int
    title: str
    blocks: tuple[DraftBlock, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "title": self.title,
            "blocks": [
                {
                    "block_id": item.block_id,
                    "kind": item.kind,
                    "title": item.title,
                    "text": item.text,
                    "items": list(item.items),
                    "columns": list(item.columns),
                    "rows": [list(row) for row in item.rows],
                    "source_id": item.source_id,
                    "asset_path": item.asset_path,
                    "level": item.level,
                }
                for item in self.blocks
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @property
    def cited_source_ids(self) -> frozenset[int]:
        return frozenset(block.source_id for block in self.blocks if block.source_id is not None)


@dataclass(frozen=True, slots=True)
class DraftPatch:
    base_version: int
    replacements: tuple[DraftBlock, ...]


def _clean(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _strings(value: Any, *, count: int, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_clean(item, limit) for item in value[:count] if _clean(item, limit))


def parse_block(value: Any) -> DraftBlock | None:
    if not isinstance(value, dict):
        return None
    block_id = _clean(value.get("block_id"), 64)
    kind = _clean(value.get("kind"), 24)
    if not _BLOCK_ID.fullmatch(block_id) or kind not in _KINDS:
        return None
    source_id = value.get("source_id")
    if source_id == 0:
        source_id = None
    if source_id is not None and (not isinstance(source_id, int) or not 1 <= source_id <= 10_000):
        return None
    if kind == "citation" and source_id is None:
        return None
    if source_id is not None and kind not in {"citation", "slide"}:
        return None
    columns = _strings(value.get("columns"), count=24, limit=500)
    rows: list[tuple[str, ...]] = []
    for raw_row in (value.get("rows") if isinstance(value.get("rows"), list) else [])[:200]:
        row = _strings(raw_row, count=24, limit=2_000)
        if columns and len(row) != len(columns):
            return None
        rows.append(row)
    asset = _clean(value.get("asset_path"), 500)
    if asset and (not _ASSET_PATH.fullmatch(asset) or ".." in asset.split("/")):
        return None
    level = value.get("level", 1)
    if not isinstance(level, int) or not 1 <= level <= 3:
        return None
    return DraftBlock(
        block_id=block_id,
        kind=kind,  # type: ignore[arg-type]
        title=_clean(value.get("title"), 500),
        text=_clean(value.get("text"), 80_000),
        items=_strings(value.get("items"), count=100, limit=4_000),
        columns=columns,
        rows=tuple(rows),
        source_id=source_id,
        asset_path=asset,
        level=level,
    )


def parse_document_draft(value: Any) -> DocumentDraft | None:
    if not isinstance(value, dict):
        return None
    title = _clean(value.get("title"), 300)
    raw_blocks = value.get("blocks")
    if not title or not isinstance(raw_blocks, list) or not 1 <= len(raw_blocks) <= 120:
        return None
    blocks: list[DraftBlock] = []
    seen: set[str] = set()
    for raw in raw_blocks:
        block = parse_block(raw)
        if block is None or block.block_id in seen:
            return None
        seen.add(block.block_id)
        blocks.append(block)
    version = value.get("version", 1)
    if not isinstance(version, int) or version < 1:
        return None
    return DocumentDraft(DRAFT_SCHEMA_VERSION, version, title, tuple(blocks))


def parse_draft_patch(value: Any) -> DraftPatch | None:
    if not isinstance(value, dict) or not isinstance(value.get("base_version"), int):
        return None
    raw = value.get("replacements")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 32:
        return None
    replacements = tuple(parse_block(item) for item in raw)
    if any(item is None for item in replacements):
        return None
    typed = tuple(item for item in replacements if item is not None)
    if len({item.block_id for item in typed}) != len(typed):
        return None
    return DraftPatch(int(value["base_version"]), typed)


def apply_draft_patch(draft: DocumentDraft, patch: DraftPatch) -> DocumentDraft | None:
    """Replace named blocks only; never add, delete, or reorder unrelated content."""

    if patch.base_version != draft.version:
        return None
    by_id = {item.block_id: item for item in patch.replacements}
    known = {item.block_id for item in draft.blocks}
    if not set(by_id).issubset(known):
        return None
    return replace(
        draft,
        version=draft.version + 1,
        blocks=tuple(by_id.get(item.block_id, item) for item in draft.blocks),
    )


def literal_draft(text: str) -> DocumentDraft:
    return DocumentDraft(
        schema_version=DRAFT_SCHEMA_VERSION,
        version=1,
        title="Документ",
        blocks=(DraftBlock("literal_text", "paragraph", text=str(text or "")[:1000]),),
    )


__all__ = [
    "DRAFT_SCHEMA_VERSION",
    "DocumentDraft",
    "DraftBlock",
    "DraftPatch",
    "apply_draft_patch",
    "literal_draft",
    "parse_block",
    "parse_document_draft",
    "parse_draft_patch",
]
