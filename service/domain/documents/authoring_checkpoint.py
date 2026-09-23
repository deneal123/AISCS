"""Validated, private checkpoint contract for resumable document authoring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .draft import DraftBlock, parse_block
from .evidence import CitationRegistry
from .evidence_bundle import DocumentEvidenceBundle
from .outline import DocumentOutline, parse_document_outline


@dataclass(frozen=True, slots=True)
class DocumentAuthoringCheckpoint:
    stage: Literal["outline", "section_authoring", "complete"]
    outline: DocumentOutline
    blocks: tuple[DraftBlock, ...]
    accepted_section_ids: tuple[str, ...]
    repair_used: bool

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "stage": self.stage,
            "outline": self.outline.payload(),
            "blocks": [asdict(block) for block in self.blocks],
            "accepted_section_ids": list(self.accepted_section_ids),
            "repair_used": self.repair_used,
        }


CheckpointWriter = Callable[[DocumentAuthoringCheckpoint], Awaitable[None]]


def allowed_outline_sources(
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
) -> frozenset[str]:
    values = set(evidence.material_source_ids if evidence is not None else ())
    if citations is not None:
        values.update(str(value) for value in citations.artifact.source_ids)
    return frozenset(values)


def restore_authoring_checkpoint(
    value: Any,
    *,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
) -> DocumentAuthoringCheckpoint | None:
    if not isinstance(value, dict):
        return None
    stage = str(value.get("stage") or "")
    if stage not in {"outline", "section_authoring", "complete"}:
        return None
    outline = parse_document_outline(
        value.get("outline"),
        allowed_source_ids=allowed_outline_sources(citations, evidence),
    )
    raw_blocks = value.get("blocks")
    raw_accepted = value.get("accepted_section_ids")
    if outline is None or not isinstance(raw_blocks, list) or not isinstance(raw_accepted, list):
        return None
    blocks = tuple(parse_block(item) for item in raw_blocks)
    if any(block is None for block in blocks):
        return None
    accepted = tuple(str(item or "") for item in raw_accepted)
    expected_prefix = tuple(section.section_id for section in outline.sections[: len(accepted)])
    if accepted != expected_prefix:
        return None
    typed_blocks = tuple(block for block in blocks if block is not None)
    cited = frozenset(block.source_id for block in typed_blocks if block.source_id is not None)
    if citations is None and cited:
        return None
    if citations is not None and not cited.issubset(citations.artifact.source_ids):
        return None
    repair_used = value.get("repair_used")
    if not isinstance(repair_used, bool):
        return None
    return DocumentAuthoringCheckpoint(
        stage=stage,  # type: ignore[arg-type]
        outline=outline,
        blocks=typed_blocks,
        accepted_section_ids=accepted,
        repair_used=repair_used,
    )


__all__ = [
    "CheckpointWriter",
    "DocumentAuthoringCheckpoint",
    "allowed_outline_sources",
    "restore_authoring_checkpoint",
]
