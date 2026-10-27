"""Opt-in isolated-worker task; never included by production Celery discovery."""

import hashlib
import logging
import os
import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import text

from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.chat.application.documents.publication import service as publication_service
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    PreparedResultCoordinator,
)
from service.services.chat.infrastructure.chat_worker.task_runtime import (
    run_coroutine,
)
from service.services.chat.infrastructure.chat_worker_tasks import (
    process_agent_message_async,
)
from service.services.chat.persistence.documents.audit import attempts as audit_attempts
from service.settings import Config

logging.disable(logging.CRITICAL)


class ForbiddenProvider:
    async def execute(self, **_kwargs):
        raise RuntimeError("acceptance_attempted_provider_execution")


async def _prepared_checkpoint(*, marker, job_id, thread_id, owner, first, task_id):
    from service.services.chat.infrastructure import chat_worker_tasks as facade

    store = celery_app.backend.client
    original_factory = facade._execution_hooks

    class SyntheticProvider:
        async def execute(self, **_kwargs):
            if not first:
                raise RuntimeError("acceptance_attempted_second_provider_execution")
            store.incr(marker + ":provider-calls")
            store.expire(marker + ":provider-calls", 240)
            return {
                "reply": "synthetic prepared result",
                "metadata": {},
                "resolved_model": "synthetic",
                "reply_parts_count": 1,
                "reply_chars_count": 25,
                "total_tokens": 33,
                "prompt_tokens": 30,
                "completion_tokens": 3,
                "per_call_usage": [
                    {
                        "model": "synthetic",
                        "prompt": 30,
                        "completion": 3,
                        "call_id": "synthetic-receipt",
                    }
                ],
            }

    class CrashAfterCommit(PreparedResultCoordinator):
        async def capture(self, **kwargs):
            await super().capture(**kwargs)
            if first:
                store.set(marker + ":first-pid", os.getpid(), ex=240)
                # Production coordinator committed the checkpoint; no charge or
                # messages have happened yet. Lose this actual prefork process.
                os._exit(73)

    async def reserve(_request, *, state, **_kwargs):
        if not first:
            raise RuntimeError("acceptance_repeated_reservation")
        state.phase.advance(RunPhase.RESERVED)
        return object(), None

    async def context(_request, **_kwargs):
        if not first:
            raise RuntimeError("acceptance_repeated_context")
        return SimpleNamespace(
            pseudo_session=None,
            file_context="",
            attachments=[],
            on_event=None,
            persona_switched=False,
            memory_parts=("", ""),
            history_messages=[],
            compact_summary="",
            tabular_files=[],
            reference_image_url=None,
            repo_graph_ids=[],
            has_non_tabular_attachment=False,
            workflow_observations=[],
            workflow_executions=[],
        )

    async def charge(**kwargs):
        execution = kwargs["execution_result"]
        if first or execution["per_call_usage"][0]["call_id"] != "synthetic-receipt":
            raise RuntimeError("acceptance_prepared_settlement_invalid")
        if execution["total_tokens"] != 33 or kwargs["pricing_inputs"] != (False, []):
            raise RuntimeError("acceptance_prepared_usage_invalid")
        store.incr(marker + ":settlements")
        store.expire(marker + ":settlements", 240)
        # Synthetic receipts exercise the settlement boundary without money.
        return 0, {**kwargs["metadata"], "usage": {"total": 33, "model": "synthetic"}}

    def hooks():
        return replace(
            original_factory(), prepared_results=CrashAfterCommit(), charge_and_describe=charge
        )

    with (
        patch.object(facade, "_execution_hooks", hooks),
        patch.object(run_execution, "_reserve_run", reserve),
        patch.object(run_execution, "_prepare_context", context),
    ):
        return await process_agent_message_async(
            job_id=job_id,
            thread_id=thread_id,
            user_id=owner,
            text="synthetic-prepared",
            memory_enabled=False,
            celery_task_id=task_id,
            agent_execution=SyntheticProvider(),
        )


@celery_app.task(
    bind=True, name="s37.acceptance.prepared-result", acks_late=True, reject_on_worker_lost=True
)
def recover_prepared_result(self, *, marker, job_id, thread_id, owner):
    if not re.fullmatch(r"s37:celery-redelivery:[0-9a-f]{32}", marker):
        raise RuntimeError("acceptance_marker_invalid")
    if thread_id != str(UUID(marker.rsplit(":", 1)[1])):
        raise RuntimeError("acceptance_prepared_fixture_invalid")
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 240)
    if attempt > 2:
        raise RuntimeError("acceptance_redelivery_limit")
    result = run_coroutine(
        _prepared_checkpoint(
            marker=marker,
            job_id=job_id,
            thread_id=thread_id,
            owner=owner,
            first=attempt == 1,
            task_id=self.request.id,
        )
    )
    if (
        result.get("status") != "success"
        or result.get("reply") != "synthetic prepared result"
        or int(store.get(marker + ":provider-calls") or 0) != 1
        or int(store.get(marker + ":settlements") or 0) != 1
        or int(store.get(marker + ":first-pid") or 0) == os.getpid()
    ):
        raise RuntimeError("acceptance_prepared_resume_invalid")
    return {
        "status": "prepared_recovered",
        "attempts": 2,
        "broker_redelivered": bool(self.request.delivery_info.get("redelivered")),
        "prefork_changed": True,
    }


async def _audit_checkpoint(*, marker, publication_id, owner, first):
    connector = PgConnector(Config().pg)
    store = celery_app.backend.client
    async with connector.get_session_context() as session:
        found = await session.execute(
            text("SELECT * FROM profile.document_publication_job WHERE id=:id AND user_id=:owner"),
            {"id": UUID(publication_id), "owner": UUID(owner)},
        )
        value = found.mappings().first()
        if value is None:
            raise RuntimeError("acceptance_audit_fixture_missing")
        row = dict(value)
        if (
            row["status"] != "terminal"
            or row["workspace_id"] != "s37-audit-" + marker.rsplit(":", 1)[1]
        ):
            raise RuntimeError("acceptance_audit_fixture_invalid")
        if first:
            attempt = await audit_attempts.begin(session, row)
            accepted = await audit_attempts.record_result(
                session,
                attempt_id=attempt["id"],
                usage={
                    "total": 33,
                    "prompt": 30,
                    "completion": 3,
                    "calls": [{"model": "synthetic", "prompt": 30, "completion": 3}],
                },
            )
            if not accepted:
                raise RuntimeError("acceptance_audit_usage_not_saved")
            await session.commit()
            store.set(marker + ":audit-id", str(attempt["id"]), ex=240)
            return
        pending = await audit_attempts.pending_charge(session, row)
        saved_id = store.get(marker + ":audit-id")
        saved_id = saved_id.decode() if isinstance(saved_id, bytes) else saved_id
        if (
            pending is None
            or str(pending["id"]) != saved_id
            or pending["usage_envelope"]["total"] != 33
        ):
            raise RuntimeError("acceptance_audit_usage_not_recovered")

        async def synthetic_charge(**kwargs):
            if (
                kwargs["execution_result"]["total_tokens"] != 33
                or kwargs["execution_result"]["prompt_tokens"] != 30
                or kwargs["execution_result"]["completion_tokens"] != 3
                or kwargs["execution_result"]["per_call_usage"]
                != [{"model": "synthetic", "prompt": 30, "completion": 3}]
                or not kwargs["require_persisted"]
                or not kwargs["job_id"].endswith(":document-audit:" + str(pending["id"]))
            ):
                raise RuntimeError("acceptance_audit_charge_contract_invalid")
            store.incr(marker + ":settlements")
            store.expire(marker + ":settlements", 240)
            return 1

        # Exercise production recovery/usage projection, but never move money
        # for a synthetic provider receipt. No vision/provider call is performed.
        with patch(
            "service.services.chat.infrastructure.chat_worker.billing.charging._charge_usage",
            synthetic_charge,
        ):
            for _ in range(2):
                await publication_service._settle_pending_audit(
                    config=Config(), pg_connector=connector, redis=None, session=session, row=row
                )
        if await audit_attempts.pending_charge(session, row) is not None:
            raise RuntimeError("acceptance_audit_settlement_missing")
        settled = await session.execute(
            text(
                "SELECT state,charge_id,usage_envelope FROM profile.document_audit_attempt "
                "WHERE id=:id AND publication_job_id=:job"
            ),
            {"id": pending["id"], "job": row["id"]},
        )
        saved = settled.mappings().one()
        if (
            saved["state"] != "settled"
            or saved["charge_id"] != "1"
            or saved["usage_envelope"]["total"] != 33
        ):
            raise RuntimeError("acceptance_audit_settlement_invalid")


@celery_app.task(
    bind=True, name="s37.acceptance.audit-checkpoint", acks_late=True, reject_on_worker_lost=True
)
def recover_audit_checkpoint(self, *, marker, publication_id, owner):
    if not re.fullmatch(r"s37:celery-redelivery:[0-9a-f]{32}", marker):
        raise RuntimeError("acceptance_marker_invalid")
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 240)
    if attempt > 2:
        raise RuntimeError("acceptance_redelivery_limit")
    run_coroutine(
        _audit_checkpoint(
            marker=marker, publication_id=publication_id, owner=owner, first=attempt == 1
        )
    )
    if attempt == 1:
        store.set(marker + ":first-pid", os.getpid(), ex=240)
        os._exit(73)
    if int(store.get(marker + ":first-pid")) == os.getpid():
        raise RuntimeError("acceptance_prefork_not_replaced")
    if int(store.get(marker + ":settlements") or 0) != 1:
        raise RuntimeError("acceptance_audit_settlement_count_invalid")
    return {
        "status": "audit_recovered",
        "attempts": 2,
        "broker_redelivered": bool(self.request.delivery_info.get("redelivered")),
        "prefork_changed": True,
    }


@celery_app.task(
    bind=True, name="s37.acceptance.redelivery", acks_late=True, reject_on_worker_lost=True
)
def replay_completed_job(self, *, marker, job_id, thread_id, owner, reply_digest):
    if not re.fullmatch(r"s37:celery-redelivery:[0-9a-f]{32}", marker):
        raise RuntimeError("acceptance_marker_invalid")
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 240)
    if attempt > 2:
        raise RuntimeError("acceptance_redelivery_limit")
    result = run_coroutine(
        process_agent_message_async(
            job_id=job_id,
            thread_id=thread_id,
            user_id=owner,
            text="synthetic-redelivery",
            memory_enabled=False,
            celery_task_id=self.request.id,
            agent_execution=ForbiddenProvider(),
        )
    )
    if (
        result.get("status") != "success"
        or hashlib.sha256(result.get("reply", "").encode()).hexdigest() != reply_digest
    ):
        raise RuntimeError("acceptance_durable_result_mismatch")
    if attempt == 1:
        store.set(marker + ":first-pid", os.getpid(), ex=240)
        # Lose the prefork child after durable result reuse, before late ACK.
        os._exit(73)
    changed = int(store.get(marker + ":first-pid")) != os.getpid()
    if not changed:
        raise RuntimeError("acceptance_prefork_not_replaced")
    return {
        "status": "reused",
        "attempts": attempt,
        "broker_redelivered": bool(self.request.delivery_info.get("redelivered")),
        "prefork_changed": changed,
    }
