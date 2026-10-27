"""Bounded semantic repair for an already accepted document draft."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict

from service.domain.client import create_chat_completion
from service.domain.documents.authoring.protocol import (
    PATCH_FUNCTION,
    PATCH_TOOL,
    response_arguments,
)
from service.domain.documents.evidence.bundle import DocumentEvidenceBundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.intent import DocumentIntent
from service.domain.documents.repair_provenance import repair_target_ids
from service.domain.documents.semantic.draft import (
    DocumentDraft,
    apply_draft_patch,
    parse_draft_patch,
)
from service.domain.documents.skills.catalog import DOCUMENT_SKILL_CATALOG
from service.domain.execution.context import RunExecutionContext
from service.domain.execution.model import invoke_model_call
from service.domain.usage.ledger import UsageKind


def _owner(execution: RunExecutionContext, model: str) -> str | None:
    return execution.provider_snapshot.owner_for(model) if execution.provider_snapshot else None


def _repair_source_ids(draft: DocumentDraft, target_ids: frozenset[str]) -> frozenset[int]:
    """Include the citation blocks normalized immediately after selected prose."""
    cited: set[int] = set()
    selected = False
    for block in draft.blocks:
        if block.block_id in target_ids:
            selected = True
        elif block.kind != "citation":
            selected = False
        if selected and block.source_id is not None:
            cited.add(block.source_id)
    return frozenset(cited)


async def repair_semantic_draft(
    intent: DocumentIntent,
    draft: DocumentDraft,
    diagnostics: list[str],
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None = None,
    evidence: DocumentEvidenceBundle | None = None,
) -> DocumentDraft | None:
    all_cited_ids = draft.cited_source_ids
    if all_cited_ids and (
        citations is None or not all_cited_ids.issubset(citations.artifact.source_ids)
    ):
        return None
    diagnostic_ids = repair_target_ids(diagnostics, draft)
    if diagnostic_ids is None:
        return None
    targets = tuple(block for block in draft.blocks if block.block_id in diagnostic_ids)
    cited_ids = _repair_source_ids(draft, frozenset(block.block_id for block in targets))
    source_context = ""
    if evidence is not None:
        projection = evidence.project_context(
            max_chars=18_000, source_ids=tuple(str(item) for item in sorted(cited_ids))
        )
        if not projection.complete or not cited_ids.issubset(projection.citation_ids):
            return None
        source_context = projection.context
    tool = deepcopy(PATCH_TOOL)
    tool["function"]["parameters"]["properties"]["replacements"]["items"]["properties"][
        "source_id"
    ]["enum"] = [0, *sorted(cited_ids)]
    tool["function"]["parameters"]["properties"]["replacements"]["items"]["properties"]["block_id"][
        "enum"
    ] = sorted(block.block_id for block in targets)
    existing = {"version": draft.version, "blocks": [asdict(item) for item in targets]}
    content = json.dumps(
        {"diagnostics": diagnostics, "draft": existing, "evidence": source_context},
        ensure_ascii=False,
    )
    if len(content) > 60_000:
        return None
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.PDF_AUTHORING,
        execution=execution,
        messages=[
            {
                "role": "system",
                "content": DOCUMENT_SKILL_CATALOG.semantic_instruction(intent.profile_id)
                + " Замени только блоки, вызвавшие перечисленные диагностические ошибки."
                + " Сохрани исходный source_id и фактический смысл каждого блока;"
                + " не добавляй, не удаляй и не подменяй ссылки на источники.",
            },
            {
                "role": "user",
                "content": content,
            },
        ],
        model=model,
        temperature=0.1,
        max_tokens=3_500,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": PATCH_FUNCTION}},
        pin_provider=_owner(execution, model),
    )
    patch = parse_draft_patch(response_arguments(result.response, PATCH_FUNCTION))
    by_id = {block.block_id: block for block in draft.blocks}
    if patch is not None and any(
        block.block_id not in by_id or block.source_id != by_id[block.block_id].source_id
        for block in patch.replacements
    ):
        return None
    if (
        patch is not None
        and diagnostic_ids
        and any(block.block_id not in diagnostic_ids for block in patch.replacements)
    ):
        return None
    repaired = apply_draft_patch(draft, patch) if patch is not None else None
    if repaired is None:
        return None
    if citations is None and repaired.cited_source_ids:
        return None
    if citations is not None and not repaired.cited_source_ids.issubset(
        citations.artifact.source_ids
    ):
        return None
    return repaired


__all__ = ["repair_semantic_draft"]
