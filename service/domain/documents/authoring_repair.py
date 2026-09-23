"""Bounded semantic repair for an already accepted document draft."""

from __future__ import annotations

import json
from dataclasses import asdict

from service.domain.client import create_chat_completion
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext
from service.domain.usage_ledger import UsageKind

from .authoring_protocol import PATCH_FUNCTION, PATCH_TOOL, response_arguments
from .draft import DocumentDraft, apply_draft_patch, parse_draft_patch
from .evidence import CitationRegistry
from .intent import DocumentIntent
from .skill_catalog import DOCUMENT_SKILL_CATALOG


def _owner(execution: RunExecutionContext, model: str) -> str | None:
    return execution.provider_snapshot.owner_for(model) if execution.provider_snapshot else None


async def repair_semantic_draft(
    intent: DocumentIntent,
    draft: DocumentDraft,
    diagnostics: list[str],
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None = None,
) -> DocumentDraft | None:
    safe_diagnostics = [str(item)[:64] for item in diagnostics[:20]]
    existing_ids = {block.block_id for block in draft.blocks}
    diagnostic_ids = {
        item.rsplit(":", 1)[1]
        for item in safe_diagnostics
        if ":" in item and item.rsplit(":", 1)[1] in existing_ids
    }
    existing = {"version": draft.version, "blocks": [asdict(item) for item in draft.blocks]}
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.PDF_AUTHORING,
        execution=execution,
        messages=[
            {
                "role": "system",
                "content": DOCUMENT_SKILL_CATALOG.semantic_instruction(intent.profile_id)
                + " Replace only blocks responsible for the bounded diagnostics.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"diagnostics": safe_diagnostics, "draft": existing}, ensure_ascii=False
                ),
            },
        ],
        model=model,
        temperature=0.1,
        max_tokens=3_500,
        tools=[PATCH_TOOL],
        tool_choice={"type": "function", "function": {"name": PATCH_FUNCTION}},
        pin_provider=_owner(execution, model),
    )
    patch = parse_draft_patch(response_arguments(result.response, PATCH_FUNCTION))
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
