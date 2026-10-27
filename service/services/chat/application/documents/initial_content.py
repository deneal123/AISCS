"""Seed only a freshly acknowledged scaffold via the existing deterministic editor.

No model call and no separate source renderer. Revision, source digest and project
lease remain authoritative. Existing or unconfirmed projects never enter this path.
"""

import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.infrastructure.pdf_workspace_binding import current_pdf_binding
from service.services.chat.application.documents.edits import render_owned_edit


@dataclass(frozen=True, slots=True)
class InitialContent:
    path: str
    expected_revision: str
    draft: dict
    authoring_version: int = 0
    draft_digest: str | None = None
    expected_source_digest: str | None = None


async def initialize_first_pdf_document(
    ref: dict, created: dict, fence: int, *, config: Any, redis: Any
) -> bool:
    payload = InitialContent(
        path=created["path"],
        expected_revision=created["revision"],
        draft={"title": "Новый документ", "text": "Начните редактирование документа здесь."},
    )
    try:
        await current_pdf_binding(redis, ref)
        rendered = await render_owned_edit(workspace_client, ref, payload, config)
        if (
            type(rendered.get("authoring_version")) is not int
            or rendered["authoring_version"] != 1
            or not all(
                isinstance(rendered.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", rendered[key])
                for key in ("draft_digest", "expected_source_digest")
            )
        ):
            return False
        await current_pdf_binding(redis, ref)
        result = await workspace_client.publish_document_source(
            ref,
            path=payload.path,
            files=rendered["files"],
            authoring_version=rendered["authoring_version"],
            draft_digest=rendered["draft_digest"],
            expected_revision=payload.expected_revision,
            expected_source_digest=rendered["expected_source_digest"],
            fence=fence,
        )
    except (
        HTTPException,
        workspace_client.WorkspaceConflict,
        workspace_client.WorkspaceUnavailable,
        workspace_client.WorkspaceRequestRejected,
    ):
        # Keep the valid source-only scaffold usable. Never render/rewrite it
        # again implicitly after an uncertain initial publication.
        return False
    return (
        isinstance(result, dict)
        and type(result.get("authoring_version")) is int
        and result["authoring_version"] == 1
    )
