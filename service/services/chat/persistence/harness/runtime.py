"""Acknowledged runtime exchanges; one owned transaction per private request."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.application.harness_capability import require_dispatch
from service.services.chat.domain.harness_state import (
    HarnessCheckpoint,
    valid_checkpoint_transition,
)
from service.services.chat.persistence.harness import effects as harness_effects
from service.services.chat.persistence.harness import grants as harness_grants
from service.services.chat.persistence.harness.admission.sealing import (
    sealed_state as _sealed_state,
)
from service.services.chat.persistence.harness.inspection import inspect_operation
from service.services.chat.persistence.harness.reservations import retain
from service.services.chat.persistence.harness.result import read_result, task_result
from service.services.chat.persistence.harness.state import (
    owned_row,
    require_active,
    save_checkpoint,
    snapshot,
)
from service.shared.harness_protocol import Continuation, HarnessFailure
from service.shared.repositories.base_repository import BaseRepository
from service.shared.task_contract import TaskState


async def _checkpoint(db, row, request, current):
    if current.state is None:
        from service.services.chat.persistence.harness.admission_checkpoint import (
            save_admission_checkpoint,
        )

        return await save_admission_checkpoint(db, row, request, current)
    continuation = request.continuation
    from service.services.chat.persistence.harness.model_requests import require_codec_transition

    require_codec_transition(current.continuation, continuation)
    from service.services.chat.persistence.harness.refinement import require_refinement_transition

    await require_refinement_transition(db, row, current, continuation)
    if continuation.clarification != current.continuation.clarification:
        raise HarnessFailure("operation_conflict")
    if (
        current.continuation.agent_name
        and continuation.agent_name != current.continuation.agent_name
    ):
        raise HarnessFailure("provider_state_incompatible")
    old_provider = current.continuation.provider
    if old_provider and (
        not continuation.provider
        or (old_provider.provider, old_provider.model)
        != (continuation.provider.provider, continuation.provider.model)
    ):
        raise HarnessFailure("provider_state_incompatible")
    if continuation.next_step < current.continuation.next_step:
        raise HarnessFailure("operation_conflict")
    if continuation.length_continuations < current.continuation.length_continuations:
        raise HarnessFailure("operation_conflict")
    new_state = request.state or current.state
    if new_state.source_revision != current.state.source_revision:
        raise HarnessFailure("binding_changed")
    if new_state != current.state:
        raw = new_state.model_dump(mode="json")
        raw["revision"] = current.state.revision + 1
        new_state = TaskState.model_validate(raw)
    # Canonical usage/budget are backend-owned; a client cannot clear holds.
    if (
        new_state.budget.spent_credits != current.state.budget.spent_credits
        or new_state.budget.held_credits != current.state.budget.held_credits
        or new_state.budget.active_ms < current.state.budget.active_ms
    ):
        raise HarnessFailure("operation_conflict")
    old = HarnessCheckpoint(state=current.state)
    new = HarnessCheckpoint(state=new_state)
    if new_state != current.state and not valid_checkpoint_transition(old, new):
        raise HarnessFailure("operation_conflict")
    # Executor receipts are required before accepting any additional evidence.
    for proof in new_state.evidence[len(current.state.evidence) :]:
        receipt = await db.scalar(
            text(
                "SELECT receipt FROM profile.harness_operation "
                "WHERE task_id=:task_id AND operation_id=:operation_id AND status='succeeded'"
            ),
            {"task_id": row["task_id"], "operation_id": UUID(proof.operation_id)},
        )
        if not receipt or proof.model_dump(mode="json") not in receipt.get("evidence", []):
            raise HarnessFailure("verification_missing")
    await save_checkpoint(db, row, state=new_state, continuation=continuation)


class HarnessRuntimeRepository(BaseRepository):
    async def _transaction(self, operation):
        try:
            async with self.connector.get_session_context() as db:
                result = await operation(db)
                await db.commit()
                return result
        except HarnessFailure:
            raise
        except Exception:
            raise HarnessFailure() from None

    async def admit(self, owner, admission, tariff, *, document_context=None):
        async def operation(db):
            job = (
                await db.execute(
                    text(
                        "SELECT j.id FROM profile.user_launch j JOIN profile.chat_threads c "
                        "ON c.thread_id=:thread_id AND c.user_id=:user_id "
                        "JOIN profile.token_reservations r ON r.reservation_id=:reservation_id "
                        "AND r.user_id=j.user_id AND r.status='reserved' AND r.expires_at>now() "
                        "AND r.tokens_reserved>=:credit_limit "
                        "WHERE j.id=:job_id AND j.user_id=:user_id AND j.type='CHAT' "
                        "AND j.status='PROCESSING' "
                        "AND j.payload->>'thread_id'=CAST(CAST(:thread_id AS uuid) AS text) "
                        "AND j.payload->>'_execution_attempt_v1'="
                        "CAST(CAST(:attempt_id AS uuid) AS text) "
                        "AND j.payload->'_execution_accounting_v1'->>'reservation_id'="
                        "CAST(CAST(:reservation_id AS uuid) AS text) "
                        "AND COALESCE(j.payload::jsonb->'_cancel_requested_v1','false'::jsonb)"
                        "<>'true'::jsonb "
                        "FOR UPDATE OF j FOR SHARE OF c"
                    ),
                    {
                        **owner.params(),
                        "reservation_id": UUID(admission.reservation_id),
                        "credit_limit": admission.credit_limit,
                    },
                )
            ).first()
            if job is None or owner.task_id != admission.task_id:
                raise HarnessFailure("harness_fenced")
            await db.execute(
                text(
                    "INSERT INTO profile.harness_task(task_id,user_id,thread_id,"
                    "execution_attempt_id,"
                    "revision,admission,continuation,tariff,active_job_id,fencing_epoch) "
                    "VALUES (:task_id,:user_id,:thread_id,:attempt_id,0,CAST(:admission AS jsonb),"
                    "'{}'::jsonb,CAST(:tariff AS jsonb),:job_id,:epoch) "
                    "ON CONFLICT(task_id) DO NOTHING"
                ),
                {
                    **owner.params(),
                    "admission": admission.model_dump_json(),
                    "tariff": tariff.model_dump_json(),
                },
            )
            row = await owned_row(db, owner)
            if row["admission"] != admission.model_dump(mode="json"):
                raise HarnessFailure("operation_conflict")
            if document_context is not None:
                from service.services.chat.persistence.harness.admission.document_scope import (
                    save_document_scope,
                )

                await save_document_scope(db, row, owner, document_context)
            await retain(
                db,
                task_id=owner.task_id,
                user_id=owner.user_id,
                reservation_id=admission.reservation_id,
                credits=admission.credit_limit,
            )
            await db.execute(
                text(
                    "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
                    "'{_harness_task_v1}',to_jsonb(CAST(:task AS text)),true) WHERE id=:job"
                ),
                {"task": owner.task_id, "job": UUID(owner.job_id)},
            )
            return await snapshot(db, row)

        return await self._transaction(operation)

    async def exchange(self, owner, request):
        async def operation(db):
            row = await owned_row(db, owner)
            current = await snapshot(db, row)
            if request.opcode in {
                "seal",
                "checkpoint",
                "grant",
                "dispatch",
                "prepare_effect",
                "dispatch_effect",
            }:
                require_active(row)
            if request.opcode in {"grant", "dispatch", "prepare_effect", "dispatch_effect"}:
                require_dispatch(current.admission)
            if (
                request.expected_revision is not None
                and request.expected_revision != row["revision"]
            ):
                raise HarnessFailure("checkpoint_conflict")
            if request.opcode == "seal":
                if current.state is not None:
                    raise HarnessFailure("operation_conflict")
                if current.admission.surface == "pdf":
                    from service.services.chat.persistence.harness.admission.document_scope import (
                        require_document_criteria,
                    )

                    await require_document_criteria(db, row, owner, request.proposal)
                from service.services.chat.persistence.harness.admission_checkpoint import (
                    require_answered,
                )

                clarification = await require_answered(db, row, current)
                state = _sealed_state(current, request.proposal)
                await save_checkpoint(
                    db,
                    row,
                    state=state,
                    continuation=Continuation(
                        phase="model",
                        provider=current.continuation.provider,
                        next_step=current.continuation.next_step,
                        clarification=clarification,
                    ),
                )
            elif request.opcode == "checkpoint":
                await _checkpoint(db, row, request, current)
            elif request.opcode == "grant":
                await self._funds(db, current)
                return {"operation": await harness_grants.allocate(db, row, request.call)}
            elif request.opcode == "dispatch":
                await self._funds(db, current)
                return {"operation": await harness_grants.dispatch(db, row, request.operation_id)}
            elif request.opcode == "call_receipt":
                return {"operation": await harness_grants.record(db, row, request.receipt)}
            elif request.opcode == "prepare_effect":
                return {
                    "operation": await harness_effects.prepare(db, row, request.effect, current)
                }
            elif request.opcode == "dispatch_effect":
                return {"operation": await harness_effects.dispatch(db, row, request.operation_id)}
            elif request.opcode == "effect_receipt":
                from service.services.chat.persistence.harness.commands.write_versions import (
                    accept_effect,
                )

                operation = await accept_effect(db, row, request.effect_result, current)
                latest = await owned_row(db, owner)
                return {
                    "operation": operation,
                    "snapshot": (await snapshot(db, latest)).model_dump(mode="json"),
                }
            elif request.opcode == "operation_status":
                status = await inspect_operation(
                    db, row, request.operation_id, request.operation_kind
                )
                return {"operation_status": status.model_dump(mode="json")}
            elif request.opcode == "result":
                return {"result": await read_result(db, row, current)}
            elif request.opcode == "lessons":
                from service.services.chat.persistence.harness.lessons import read_lessons

                return {"lessons": await read_lessons(db, row, current)}
            row = await owned_row(db, owner)
            return {"snapshot": (await snapshot(db, row)).model_dump(mode="json")}

        return await self._transaction(operation)

    @staticmethod
    async def _funds(db, current):
        valid = await db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM profile.token_reservations WHERE reservation_id=:id "
                "AND harness_task_id=:task AND status='reserved' "
                "AND expires_at>now() AND tokens_reserved>=:limit)"
            ),
            {
                "id": UUID(current.admission.reservation_id),
                "task": UUID(current.admission.task_id),
                "limit": current.admission.credit_limit - current.settled_credits,
            },
        )
        if valid is not True:
            raise HarnessFailure("budget_unavailable")

    _result = staticmethod(task_result)
