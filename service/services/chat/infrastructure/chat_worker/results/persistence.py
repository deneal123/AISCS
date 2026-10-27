"""Stage one charged turn and its outbox intent in the caller-owned transaction.

No commit, broker notification or public reply happens here. The returned flag
requests a delivery wakeup only after the caller has acknowledged its commit;
it is not evidence that an artifact has been delivered.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.context.metadata import (
    persistable_meta,
    user_message_meta,
)
from service.services.chat.infrastructure.chat_worker.results.document_publication import (
    document_origin_message_id,
    enqueue_document_intent,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    WorkerExecutionHooks,
    WorkerRunRequest,
)


async def stage_turn_success(
    request: WorkerRunRequest,
    *,
    reply: str,
    file_url: str | None,
    metadata: dict[str, Any],
    engine_env: dict[str, Any] | None,
    session: Any,
    job_repo: Any,
    hooks: WorkerExecutionHooks,
) -> bool:
    """Stage messages -> document intent -> terminal job status, without committing.

    Metadata is the caller's mutable public projection, not its private terminal
    frame. Strip delivery descriptors before either assistant or job persistence.
    Confirmation/question continuations reuse the original user turn.
    """
    publication_descriptors = metadata.pop("_document_publications", None)
    publication_origin = (
        document_origin_message_id(request.job_id) if publication_descriptors else None
    )
    confirmed_offer = (
        bool((request.session_data or {}).get("confirmed_offer_id"))
        or request.question_resume is not None
    )
    target = (request.session_data or {}).get("_document_context") or {}
    document_meta = {"document_project": target["project_id"]} if target.get("project_id") else {}
    ide_target = (request.session_data or {}).get("_ide_context") or {}
    if ide_target.get("repository_id"):
        document_meta["ide_repository"] = ide_target["repository_id"]
    metadata.update(document_meta)
    await hooks.persist_chat_turn(
        db_session=session,
        thread_id=request.thread_id,
        user_text="" if confirmed_offer else request.text,
        assistant_text=reply,
        user_id=request.user_id,
        user_metadata={}
        if confirmed_offer
        else {**user_message_meta(request.attachments), **document_meta},
        assistant_metadata=persistable_meta(metadata, file_url),
        **({"assistant_message_id": publication_origin} if publication_origin else {}),
        **(
            {"user_message_id": str(uuid5(NAMESPACE_URL, f"chat-offer:{request.job_id}"))}
            if metadata.get("awaiting_confirmation")
            else {}
        ),
    )
    workspace_ref = engine_env.get("workspace_ref") if engine_env else None
    if publication_origin is not None and isinstance(workspace_ref, dict):
        await enqueue_document_intent(
            session,
            user_id=request.user_id,
            thread_id=request.thread_id,
            workspace_id=str(workspace_ref.get("workspace_id") or ""),
            job_id=request.job_id,
            descriptors=publication_descriptors,
            origin_message_id=publication_origin,
        )
    await hooks.update_job_status(
        job_repo,
        request.job_id,
        ProcessingStatus.SUCCESS,
        session,
        request.user_id,
        {"reply": reply, "file_url": file_url, "metadata": metadata},
    )
    return bool(publication_descriptors)
