"""Revalidate private project selection before reservation, independently of queue transport."""

from typing import Any

from service.composition.ide import build_ide_runtime
from service.services.chat.application.ide.agent_context import resolve_ide_target
from service.services.chat.domain.documents.context import DocumentContext
from service.services.chat.domain.ide.edits import IdeEditError


async def validate_run_targets(request: Any, redis: Any, connector: Any) -> dict | None:
    data = request.session_data or {}
    document, ide = data.get("_document_context"), data.get("_ide_context")
    if document is not None and ide is not None:
        raise IdeEditError("ide_agent_context_invalid")
    validated_document = None
    if isinstance(document, dict):
        from service.services.chat.application.documents.context import validate_document_context

        validated_document = await validate_document_context(
            redis,
            request.thread_id,
            str(request.user_id or ""),
            {key: value for key, value in document.items() if key in DocumentContext.model_fields},
        )
        data["_document_context"] = validated_document
    if ide is not None:
        target, _ = await resolve_ide_target(
            build_ide_runtime(connector), request.thread_id, str(request.user_id or ""), ide
        )
        data["_ide_context"] = target.model_dump(mode="json")
    return validated_document
