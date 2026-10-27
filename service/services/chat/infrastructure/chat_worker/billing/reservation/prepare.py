"""Owned target validation and credit reservation before provider dispatch."""

from typing import Any

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.agent_context import create_session
from service.services.chat.infrastructure.chat_worker.context.attachment_evidence import (
    owner_checked_attachments,
)
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerExecutionHooks,
    WorkerRunRequest,
)


async def _reserve_run(
    request: WorkerRunRequest,
    *,
    config: Any,
    pg_connector: Any,
    publisher: Any,
    job_repo: Any,
    session: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    redis_client: Any,
    file_service: Any,
) -> tuple[Any, dict[str, Any] | None]:
    from service.services.chat.application.documents.context import document_tools_auto_approved
    from service.services.chat.infrastructure.chat_worker.context.targets import (
        validate_run_targets,
    )

    validated_document = await validate_run_targets(request, redis_client, pg_connector)
    await hooks.update_job_status(
        job_repo,
        request.job_id,
        ProcessingStatus.PROCESSING,
        session,
        request.user_id,
    )
    confirmed_offer_id = str((request.session_data or {}).get("confirmed_offer_id") or "")
    if confirmed_offer_id:
        from service.services.chat.domain.confirmation.offer import mark_persisted_offer_accepted

        await mark_persisted_offer_accepted(
            session,
            thread_id=request.thread_id,
            offer_id=confirmed_offer_id,
            decision=(request.session_data or {}).get("confirmation_decision", "accept"),
        )
        await session.commit()
    pseudo_session = create_session(
        session_id=(request.session_data or {}).get("session_id", request.thread_id)
    )
    if request.question_resume is None:
        await hooks.restore_history(
            pseudo_session=pseudo_session,
            db_session=session,
            thread_id=request.thread_id,
            session_data=request.session_data,
            history_limit=max(getattr(config.agents, "chat_history_messages_limit", 8), 1),
        )
    safe_attachments = await owner_checked_attachments(
        file_service,
        user_id=request.user_id,
        file_ids=(request.session_data or {}).get("file_ids"),
        attachments=request.attachments,
        redis=redis_client,
    )
    context_chars = hooks.reservation_context_chars(
        file_context=request.file_context,
        pseudo_session=pseudo_session,
        attachments=safe_attachments,
    )
    if request.question_resume is not None:
        context_chars = len(request.question_resume.messages_json)
    target = (request.session_data or {}).get("_document_context")
    if isinstance(target, dict):
        context_chars += len(str(target.get("content") or "")) + 700
    if state.harness_recovered:
        state.phase.advance(RunPhase.RESERVED)
        return pseudo_session, None
    short_circuit, state.reservation_id, state.reserved_estimate = await hooks.reserve_credits(
        pg_connector=pg_connector,
        config=config,
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=request.job_id,
        thread_id=request.thread_id,
        text=request.text,
        user_id=request.user_id,
        selected_model=request.selected_model,
        context_chars=context_chars,
        attachments=safe_attachments,
        expensive_run_confirmed=bool((request.session_data or {}).get("confirm_expensive_run"))
        or document_tools_auto_approved(
            validated_document, (request.session_data or {}).get("confirmation_decision")
        ),
        redis_client=redis_client,
        confirmation_context={
            **({"harness_credit_limit": state.harness_remaining} if state.harness_task_id else {}),
            **(
                {"skip_user_turn": True, "question_cost": request.question_resume.cost}
                if request.question_resume is not None
                else {}
            ),
            "ide_context": (request.session_data or {}).get("_ide_context"),
            "document_context": {
                key: value
                for key, value in (
                    (request.session_data or {}).get("_document_context") or {}
                ).items()
                if key
                in {"path", "expected_revision", "authoring_version", "draft_digest", "block_ids"}
            }
            or None,
            "route_override": request.route_override,
            "resolved_category": (request.session_data or {}).get("_resolved_category"),
            "input_type": request.input_type,
            "file_ids": (request.session_data or {}).get("file_ids") or [],
        },
    )
    if short_circuit is not None:
        await session.commit()
        return pseudo_session, short_circuit
    state.phase.advance(RunPhase.RESERVED)
    return pseudo_session, None
