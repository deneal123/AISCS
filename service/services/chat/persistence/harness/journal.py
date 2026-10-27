"""PostgreSQL authority for checkpoints and once-only dispatch admission.

Every method owns its transaction by default: an ACK follows commit, never just
flush. A lost ACK requires read/reconciliation, not another effect dispatch.
This journal deliberately does not reserve/settle money or execute commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.harness_state import (
    HarnessCheckpoint,
    OperationIntent,
    OperationReceipt,
    receipt_matches,
    valid_checkpoint_transition,
)
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session
from service.shared.task_contract import CompletionVerifier


@dataclass(frozen=True, slots=True)
class HarnessScope:
    job_id: UUID
    user_id: UUID
    thread_id: UUID
    attempt_id: UUID
    project_id: str
    generation: str

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "job": self.job_id,
            "owner": self.user_id,
            "thread": str(self.thread_id),
            "attempt": str(self.attempt_id),
        }


async def _fence(db: AsyncSession, scope: HarnessScope, *, active: bool) -> bool:
    row = (
        (
            await db.execute(
                text(
                    "SELECT j.status,j.payload FROM profile.user_launch j "
                    "JOIN profile.chat_threads t ON t.thread_id=CAST(:thread AS uuid) "
                    "AND t.user_id=:owner WHERE j.id=:job AND j.user_id=:owner AND j.type='CHAT' "
                    "AND j.payload->>'thread_id'=CAST(:thread AS text) "
                    "AND j.payload->>'_execution_attempt_v1'=:attempt "
                    "FOR UPDATE OF j FOR SHARE OF t"
                ),
                scope.parameters,
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return False
    payload = row["payload"]
    return not active or (
        row["status"] == "PROCESSING"
        and payload.get("_cancel_requested_v1") is not True
        and not any(
            key in payload
            for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
        )
    )


async def _load(db: AsyncSession, scope: HarnessScope) -> HarnessCheckpoint | None:
    row = (
        (
            await db.execute(
                text(
                    "SELECT checkpoint,checkpoint_digest FROM profile.harness_task "
                    "WHERE task_id=:job AND user_id=:owner "
                    "AND thread_id=CAST(:thread AS uuid) "
                    "AND execution_attempt_id=CAST(:attempt AS uuid) FOR UPDATE"
                ),
                scope.parameters,
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    checkpoint = HarnessCheckpoint.model_validate(row["checkpoint"])
    contract = checkpoint.state.contract
    if (
        contract.task_id != str(scope.job_id)
        or contract.project_id != scope.project_id
        or contract.generation != scope.generation
        or checkpoint.digest != row["checkpoint_digest"]
    ):
        return None
    return checkpoint


async def _operation(db: AsyncSession, scope: HarnessScope, operation_id: str):
    return (
        (
            await db.execute(
                text(
                    "SELECT intent,intent_digest,status,receipt FROM profile.harness_operation "
                    "WHERE task_id=:job AND operation_id=CAST(:op AS uuid) FOR UPDATE"
                ),
                {"job": scope.job_id, "op": operation_id},
            )
        )
        .mappings()
        .first()
    )


async def _evidence_recorded(db: AsyncSession, scope: HarnessScope, old, new) -> bool:
    for evidence in new.state.evidence[len(old.state.evidence) :]:
        row = await _operation(db, scope, evidence.operation_id)
        if row is None or row["receipt"] is None:
            return False
        receipt = OperationReceipt.model_validate(row["receipt"])
        if evidence not in receipt.evidence:
            return False
    return True


async def _uncertain_effect(db: AsyncSession, scope: HarnessScope) -> bool:
    return bool(
        await db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:job "
                "AND status IN ('dispatched','unknown') AND intent->>'action'<>'read')"
            ),
            {"job": scope.job_id},
        )
    )


class HarnessRepository(BaseRepository):
    @connection()
    async def create(
        self,
        scope: HarnessScope,
        checkpoint: HarnessCheckpoint,
        *,
        session: AsyncSession | None = None,
    ) -> HarnessCheckpoint | None:
        db = require_session(session)
        if not await _fence(db, scope, active=True):
            return None
        state = checkpoint.state
        if (
            state.contract.task_id != str(scope.job_id)
            or state.contract.project_id != scope.project_id
            or state.contract.generation != scope.generation
            or state.revision != 0
            or state.rounds
            or state.repairs
            or state.protocol_repairs
            or state.evidence
            or state.cancelled
            or checkpoint.provider
            or state.budget.spent_credits
            or state.budget.held_credits
            or state.budget.active_ms
        ):
            return None
        await db.execute(
            text(
                "INSERT INTO profile.harness_task "
                "(task_id,user_id,thread_id,execution_attempt_id,"
                "checkpoint,checkpoint_digest,revision) "
                "VALUES (:job,:owner,CAST(:thread AS uuid),CAST(:attempt AS uuid),"
                "CAST(:body AS jsonb),:digest,0) ON CONFLICT(task_id) DO NOTHING"
            ),
            {**scope.parameters, "body": checkpoint.model_dump_json(), "digest": checkpoint.digest},
        )
        loaded = await _load(db, scope)
        return loaded if loaded and loaded.digest == checkpoint.digest else None

    @connection()
    async def read(
        self,
        scope: HarnessScope,
        *,
        session: AsyncSession | None = None,
    ) -> HarnessCheckpoint | None:
        db = require_session(session)
        return await _load(db, scope) if await _fence(db, scope, active=False) else None

    @connection()
    async def checkpoint(
        self,
        scope: HarnessScope,
        checkpoint: HarnessCheckpoint,
        *,
        session: AsyncSession | None = None,
    ) -> bool:
        db = require_session(session)
        if not await _fence(db, scope, active=True):
            return False
        old = await _load(db, scope)
        if old is None:
            return False
        if old.digest == checkpoint.digest:
            return True  # Exact redelivery after a lost commit ACK.
        if not valid_checkpoint_transition(old, checkpoint):
            return False
        if not await _evidence_recorded(db, scope, old, checkpoint):
            return False
        await db.execute(
            text(
                "UPDATE profile.harness_task SET checkpoint=CAST(:body AS jsonb),"
                "checkpoint_digest=:digest,revision=:revision,updated_at=now() WHERE task_id=:job"
            ),
            {
                "job": scope.job_id,
                "body": checkpoint.model_dump_json(),
                "digest": checkpoint.digest,
                "revision": checkpoint.state.revision,
            },
        )
        return True

    @connection()
    async def prepare(
        self,
        scope: HarnessScope,
        intent: OperationIntent,
        *,
        session: AsyncSession | None = None,
    ) -> bool:
        db = require_session(session)
        if not await _fence(db, scope, active=True):
            return False
        checkpoint = await _load(db, scope)
        if checkpoint is None:
            return False
        state = checkpoint.state
        criteria = {item.criterion_id for item in state.contract.criteria}
        if (
            state.cancelled
            or state.source_revision != intent.source_revision
            or set(intent.criterion_ids) - criteria
            or intent.action not in state.contract.actions
        ):
            return False
        if intent.action != "read" and await _uncertain_effect(db, scope):
            # Existing intent may be queried/reconciled, but not dispatched again.
            row = await _operation(db, scope, intent.operation_id)
            return row is not None and row["intent_digest"] == intent.digest
        await db.execute(
            text(
                "INSERT INTO profile.harness_operation(task_id,operation_id,intent,intent_digest) "
                "VALUES (:job,CAST(:op AS uuid),CAST(:body AS jsonb),:digest) "
                "ON CONFLICT(task_id,operation_id) DO NOTHING"
            ),
            {
                "job": scope.job_id,
                "op": intent.operation_id,
                "body": intent.model_dump_json(),
                "digest": intent.digest,
            },
        )
        row = await _operation(db, scope, intent.operation_id)
        return row is not None and row["intent_digest"] == intent.digest

    @connection()
    async def dispatch(
        self,
        scope: HarnessScope,
        intent: OperationIntent,
        *,
        session: AsyncSession | None = None,
    ) -> bool:
        """True only once. False is never permission to repeat the external effect."""
        db = require_session(session)
        if not await _fence(db, scope, active=True):
            return False
        checkpoint = await _load(db, scope)
        if checkpoint is None or checkpoint.state.cancelled:
            return False
        if checkpoint.state.source_revision != intent.source_revision:
            return False
        row = await _operation(db, scope, intent.operation_id)
        if row is None or row["intent_digest"] != intent.digest or row["status"] != "prepared":
            return False
        if intent.action != "read" and await _uncertain_effect(db, scope):
            return False
        await db.execute(
            text(
                "UPDATE profile.harness_operation SET status='dispatched',updated_at=now() "
                "WHERE task_id=:job AND operation_id=CAST(:op AS uuid)"
            ),
            {"job": scope.job_id, "op": intent.operation_id},
        )
        return True

    @connection()
    async def receipt(
        self,
        scope: HarnessScope,
        intent: OperationIntent,
        receipt: OperationReceipt,
        *,
        reconciled: bool = False,
        session: AsyncSession | None = None,
    ) -> bool:
        db = require_session(session)
        if not await _fence(db, scope, active=False):
            return False
        checkpoint = await _load(db, scope)
        row = await _operation(db, scope, intent.operation_id)
        if checkpoint is None or row is None or row["intent_digest"] != intent.digest:
            return False
        if row["receipt"] == receipt.model_dump(mode="json"):
            return True
        if row["status"] != "dispatched" and not (row["status"] == "unknown" and reconciled):
            return False
        if not receipt_matches(intent, receipt, checkpoint.state):
            return False
        await db.execute(
            text(
                "UPDATE profile.harness_operation SET status=:status,receipt=CAST(:body AS jsonb),"
                "updated_at=now() WHERE task_id=:job AND operation_id=CAST(:op AS uuid)"
            ),
            {
                "job": scope.job_id,
                "op": intent.operation_id,
                "status": receipt.status,
                "body": receipt.model_dump_json(),
            },
        )
        return True

    @connection()
    async def operation_status(
        self,
        scope: HarnessScope,
        intent: OperationIntent,
        *,
        session: AsyncSession | None = None,
    ) -> dict | None:
        db = require_session(session)
        if not await _fence(db, scope, active=False) or await _load(db, scope) is None:
            return None
        row = await _operation(db, scope, intent.operation_id)
        if row is None or row["intent_digest"] != intent.digest:
            return None
        return {"status": row["status"], "receipt": row["receipt"]}

    @connection()
    async def completion(
        self,
        scope: HarnessScope,
        *,
        session: AsyncSession | None = None,
    ) -> dict | None:
        db = require_session(session)
        if not await _fence(db, scope, active=False):
            return None
        checkpoint = await _load(db, scope)
        if checkpoint is None:
            return None
        pending = await db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:job "
                "AND status IN ('prepared','dispatched','unknown'))"
            ),
            {"job": scope.job_id},
        )
        cancelled = await db.scalar(
            text(
                "SELECT payload::jsonb->'_cancel_requested_v1'='true'::jsonb "
                "FROM profile.user_launch WHERE id=:job"
            ),
            {"job": scope.job_id},
        )
        state = checkpoint.state.advance(cancelled=True) if cancelled else checkpoint.state
        return CompletionVerifier.evaluate(state, pending_operations=bool(pending))
