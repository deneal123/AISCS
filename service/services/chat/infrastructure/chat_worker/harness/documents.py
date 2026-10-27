"""Продолжение PDF сохраняет корневое выделение и проверяет актуальность исходников."""

from fastapi import HTTPException

from service.infrastructure.workspace_client import (
    WorkspaceConflict,
    WorkspaceGone,
    WorkspaceUnavailable,
)
from service.services.chat.application.documents.context import validate_document_context
from service.services.chat.persistence.harness.admission.document_scope import (
    load_owned_document_scope,
)
from service.shared.harness_protocol import HarnessFailure


async def resume_document_context(connector, redis, owner, reference):
    scope = await load_owned_document_scope(connector, owner)
    received = reference.get("document_context") or {}
    if any(received.get(key) != value for key, value in scope.items()):
        raise HarnessFailure("binding_changed")
    try:
        return await validate_document_context(
            redis,
            owner.thread_id,
            owner.user_id,
            scope,
            expected_workspace_id=owner.generation,
        )
    except HTTPException as error:
        code = "project_unavailable" if error.status_code == 404 else "binding_changed"
        raise HarnessFailure(code) from None
    except WorkspaceConflict:
        raise HarnessFailure("binding_changed") from None
    except WorkspaceGone:
        raise HarnessFailure("project_unavailable") from None
    except WorkspaceUnavailable:
        raise HarnessFailure("checkpoint_unavailable") from None
