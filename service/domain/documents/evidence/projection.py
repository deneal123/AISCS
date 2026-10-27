"""Private source projection bound to the document's canonical citation registry."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from service.domain.documents.evidence.mentions import referenced_citations

if TYPE_CHECKING:
    from service.domain.documents.evidence.bundle import DocumentEvidenceBundle

EVIDENCE_PROJECTION_VERSION = 3


@dataclass(frozen=True, slots=True)
class EvidencePromptProjection:
    context: str = field(repr=False)
    included_blocks: int
    omitted_blocks: int
    citation_ids: frozenset[int] = field(default_factory=frozenset, repr=False)

    @property
    def complete(self) -> bool:
        """All registered prompt blocks fit; not an attestation of raw input coverage."""
        return self.omitted_blocks == 0


def _blocks(
    bundle: DocumentEvidenceBundle, selected: frozenset[str] | None
) -> Iterator[tuple[str, str]]:
    linked_citations: set[int] = set()
    for attachment in bundle.attachments:
        for chunk in attachment.chunks:
            if selected is None or chunk.source_id in selected:
                if selected is not None:
                    linked_citations.update(
                        referenced_citations(chunk.text, bundle.bibliography.records)
                    )
                yield chunk.source_id, chunk.prompt_block()

    # Research IDs belong to its own registry, not the merged bibliography.
    # Project through canonical URL and retain the final citation identity and
    # supplied metadata. Retrieved bodies remain actual evidence, not model text.
    retrieved = (
        {record.canonical_url: record for record in bundle.research.records}
        if bundle.research is not None
        else {}
    )
    for record in bundle.bibliography.records:
        if (
            selected is not None
            and str(record.source_id) not in selected
            and record.source_id not in linked_citations
        ):
            continue
        source = retrieved.get(record.canonical_url)
        projected = replace(record, content=source.content) if source is not None else record
        yield str(record.source_id), projected.synthesis_block(max_chars=2_400)


def project_evidence_context(
    bundle: DocumentEvidenceBundle,
    *,
    max_chars: int,
    source_ids: Iterable[str] | None,
) -> EvidencePromptProjection:
    """Explicit selection never falls back to unrelated sources or renumbers IDs.

    This is a bounded prompt view, not a completeness attestation. Input objects,
    digest, citation keys and checkpoints remain unchanged by projection.
    """
    selected = frozenset(source_ids) if source_ids is not None else None
    candidates = tuple(_blocks(bundle, selected))
    unresolved = len(selected - {source_id for source_id, _ in candidates}) if selected else 0
    limit = max(0, max_chars)
    blocks: list[str] = []
    used = 0
    included = 0
    visible: set[str] = set()
    for source_id, block in candidates:
        separator = 2 if blocks else 0
        remaining = limit - used - separator
        if len(block) > remaining:
            if remaining >= 256:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
        included += 1
        visible.add(source_id)
        used += len(block) + separator
    return EvidencePromptProjection(
        "\n\n".join(blocks),
        included,
        len(candidates) - included + unresolved,
        frozenset(
            record.source_id
            for record in bundle.bibliography.records
            if str(record.source_id) in visible
        ),
    )
