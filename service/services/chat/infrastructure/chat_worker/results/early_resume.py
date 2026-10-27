"""Early accepted facts survive artifact/catalog failures without another model call."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from service.infrastructure.agents_client.ports import resolve_user_uuid
from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.materialization.builder import (
    build_materialization_plan,
)
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
    MATERIALIZATION_KEY,
    MaterializationPlan,
    recover_materialization,
    stage_materialization,
)
from service.services.chat.infrastructure.chat_worker.materialization.workspace import (
    recover_workspace_files,
)
from service.services.chat.infrastructure.chat_worker.results.accepted import (
    accepted_turn,
    decode_accepted,
    promote_accepted,
    stage_accepted,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    ACCEPTED_KEY,
    CHECKPOINT_KEY,
    PreparedTurnCheckpoint,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    _CALL_FIELDS,
    _USAGE_FIELDS,
    _reply_projection,
    _safe_files,
)


async def capture_accepted(
    *,
    request: Any,
    repository: Any,
    session: Any,
    state: Any,
    execution_result: dict,
    reply: str,
    metadata: dict,
    prepared: Any,
    started_at: float,
) -> None:
    try:
        owner = resolve_user_uuid(request.user_id, anonymous_fallback=True)
        usage = {key: execution_result[key] for key in _USAGE_FIELDS if key in execution_result}
        usage["per_call_usage"] = [
            {key: value for key, value in call.items() if key in _CALL_FIELDS}
            for call in execution_result.get("per_call_usage") or []
            if isinstance(call, dict)
        ]
        accepted = accepted_turn(
            job_id=request.job_id,
            owner_id=str(owner),
            thread_id=request.thread_id,
            reply=reply,
            model=execution_result.get("resolved_model"),
            usage=usage,
        )
        try:
            from service.services.chat.infrastructure.chat_worker.continuation.pause import (
                prepare_question,
                stage_question,
            )

            pause = prepare_question(request, state, execution_result, reply)
            if pause is not None:
                await stage_question(
                    pause, repository=repository, session=session, metadata=metadata
                )
            plan = build_materialization_plan(
                metadata=metadata,
                execution_result=execution_result,
                state=state,
                prepared=prepared,
                started_at=started_at,
            )
        except Exception:
            # A bad replay projection cannot erase incurred model facts or permit
            # another model invocation. Preserve a bare latch for bounded refusal.
            await stage_accepted(repository, session, accepted)
            await session.commit()
            raise JobStateUnavailable("Prepared result unavailable") from None
        await stage_materialization(repository, session, accepted, plan)
        await session.commit()
        row = await repository.lock_prepared_turn(UUID(request.job_id), owner, session=session)
        if (
            row is None
            or row["status"] != ProcessingStatus.PROCESSING
            or row["payload"].get(ACCEPTED_KEY) != accepted.payload()
            or row["payload"].get(MATERIALIZATION_KEY) != plan.payload()
            or CHECKPOINT_KEY in row["payload"]
        ):
            raise JobStateUnavailable("Prepared result unavailable")
        state.accepted_captured = True
    except Exception:
        raise JobStateUnavailable("Prepared result unavailable") from None


async def restore_accepted(
    *,
    request: Any,
    repository: Any,
    session: Any,
    file_service: Any,
    payload: dict,
    catalog_recorder: Any,
    redis_client: Any = None,
) -> dict:
    """Promote under the existing owner lock; catalog and prepared latch commit together."""
    owner = resolve_user_uuid(request.user_id, anonymous_fallback=True)
    accepted = decode_accepted(
        payload.get(ACCEPTED_KEY),
        job_id=request.job_id,
        owner_id=str(owner),
        thread_id=request.thread_id,
    ).payload()["body"]
    from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
        require_stored_usage,
    )

    require_stored_usage(accepted["usage"], payload)
    from service.services.chat.infrastructure.chat_worker.billing.reservation.recovery import (
        require_reservation_projection,
        verify_accounting,
    )

    accounting = await verify_accounting(session, payload, request)
    plan = MaterializationPlan.from_payload(payload.get(MATERIALIZATION_KEY))
    require_reservation_projection(accounting, plan.payload())
    recovered = await recover_materialization(plan, owner_id=str(owner), file_service=file_service)
    facts = plan.payload()
    public = dict(recovered["metadata"])
    public.pop("_document_publications", None)
    public = await recover_workspace_files(
        request=request,
        facts=facts,
        metadata=public,
        file_service=file_service,
        redis_client=redis_client,
    )
    from service.services.chat.infrastructure.chat_worker.continuation.pause import (
        verify_question_reference,
    )

    await verify_question_reference(
        request=request, repository=repository, session=session, metadata=public
    )
    public = persistable_meta(public, None)
    if "generated_files" in public:
        public["generated_files"] = _safe_files(public)
    private = {
        key: facts[key]
        for key in (
            "reservation_id",
            "reserved_estimate",
            "workspace_id",
            "expires_at",
            "publications",
            "pricing",
            "elapsed_seconds",
        )
    }
    private["primary_file_id"] = None
    displayed = accepted["reply"]
    if any(item["required"] for item in facts.get("workspace_files", [])):
        from service.infrastructure.agents_client.required_artifacts import DELIVERY_READY_REPLY

        displayed = DELIVERY_READY_REPLY
        projection = _reply_projection(accepted["reply"], displayed, public)
        if projection is not None:
            private["reply_projection"] = projection
    checkpoint = PreparedTurnCheckpoint.create(
        job_id=request.job_id,
        owner_id=str(owner),
        thread_id=request.thread_id,
        reply=accepted["reply"],
        model=accepted["model"],
        usage=accepted["usage"],
        metadata={"public": public, "private": private},
    )
    catalog = recovered["catalog"]
    if catalog["observations"] or catalog["executions"]:
        if catalog_recorder is None:
            raise JobStateUnavailable("Prepared result unavailable")
        await catalog_recorder(
            session,
            **catalog,
            thread_id=request.thread_id,
            user_id=str(owner),
            reply=displayed,
        )
    plan.validate_promotion(checkpoint.payload()["body"]["metadata"])
    await promote_accepted(repository, session, checkpoint)
    await session.commit()
    row = await repository.lock_prepared_turn(UUID(request.job_id), owner, session=session)
    if (
        row is None
        or row["status"] != ProcessingStatus.PROCESSING
        or row["payload"].get(CHECKPOINT_KEY) != checkpoint.payload()
    ):
        raise JobStateUnavailable("Prepared result unavailable")
    return checkpoint.payload()
