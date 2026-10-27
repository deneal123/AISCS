"""Validate a document target against the owned workspace before routing or billing."""

from __future__ import annotations

import json

from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.services.chat.domain.documents.context import DocumentContext, document_project_id


async def validate_document_context(
    redis,
    thread_id: str,
    user_id: str,
    raw: dict | None,
    *,
    expected_workspace_id: str | None = None,
) -> dict | None:
    if raw is None:
        return None
    try:
        context = DocumentContext.model_validate(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="document_context_invalid") from None
    ref = await workspace_client.read_binding(redis, thread_id)
    if not ref or str(ref.get("user_id") or "") != str(user_id):
        raise HTTPException(status_code=404, detail="document_project_not_found")
    if expected_workspace_id is not None and ref.get("workspace_id") != expected_workspace_id:
        raise HTTPException(status_code=409, detail="source_changed")
    project = await workspace_client.document_project_status(ref, path=context.path)
    if not isinstance(project, dict):
        raise HTTPException(status_code=404, detail="document_project_not_found")
    if any(
        project.get(key) != getattr(context, key) for key in ("authoring_version", "draft_digest")
    ) or (project.get("revision") != context.expected_revision):
        raise HTTPException(status_code=409, detail="source_changed")
    state = None
    if context.authoring_version:
        state = await workspace_client.document_authoring_state(ref, path=context.path)
        known = {
            block.get("block_id") for block in (state or {}).get("draft", {}).get("blocks", [])
        }
        if not set(context.block_ids).issubset(known):
            raise HTTPException(status_code=409, detail="source_changed")
    elif context.block_ids:
        raise HTTPException(status_code=422, detail="document_context_invalid")
    return {
        **context.model_dump(),
        "project_id": document_project_id(user_id, thread_id, context.path),
        # PDF Studio submission is standing consent for tools in this owned run.
        # This is derived after authorization/version checks, never accepted from a DTO.
        "tools_auto_approved": True,
        # Приватное согласование server/agents/UI, не полномочие из входного DTO.
        "patch_version": 2,
        # Private run context, not trace/metadata. Rendering treats it as untrusted content.
        "content": json.dumps((state or {}).get("draft") or {}, ensure_ascii=False),
    }


def document_tools_auto_approved(context: dict | None, decision: str | None = None) -> bool:
    """Private, validated project policy; never override an explicit legacy decline."""
    return bool(
        isinstance(context, dict)
        and context.get("tools_auto_approved") is True
        and context.get("project_id")
        and context.get("path")
        and decision != "decline"
    )
