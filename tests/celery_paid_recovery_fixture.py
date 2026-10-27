"""Explicit opt-in dev task: actual model usage, actual charge, then prefork loss.

Never included by production task discovery. This fixture does not manufacture
receipts or move money for synthetic calls. The controller preserves real billing
events while removing only its temporary job/thread/workspace after acceptance.
"""

import hashlib
import logging
import os
import re
from dataclasses import replace
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import text

from service.infrastructure.agents_client.engine_factory import select_agent_engine
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.chat.infrastructure import chat_worker_tasks as facade
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    PreparedResultCoordinator,
)
from service.services.chat.infrastructure.chat_worker.task_runtime import run_coroutine
from service.settings import Config

logging.disable(logging.CRITICAL)

MODEL = "GigaChat-2"
MAX_ESTIMATE = 5000
REQUEST = "Ответь ровно одним словом: тест. Не используй инструменты."


async def _owned_fixture(job_id, thread_id, owner):
    connector = PgConnector(Config().pg)
    async with connector.get_session_context() as session:
        found = await session.scalar(
            text(
                "SELECT count(*) FROM profile.user_launch j "
                'JOIN profile."user" u ON u.id=j.user_id '
                "WHERE j.id=:job AND j.user_id=:owner AND u.email=:email "
                "AND j.payload->>'thread_id'=:thread "
                "AND j.payload->>'acceptance_fixture'='s37-paid-recovery'"
            ),
            {
                "job": UUID(job_id),
                "owner": UUID(owner),
                "thread": thread_id,
                "email": "s37-e2e-391e5206659a3654@example.com",
            },
        )
        if found != 1:
            raise RuntimeError("acceptance_paid_fixture_invalid")


async def _run_paid(*, marker, job_id, thread_id, owner, first, task_id):
    await _owned_fixture(job_id, thread_id, owner)
    store = celery_app.backend.client
    original_factory = facade._execution_hooks

    def save(suffix, value):
        store.set(marker + suffix, value, ex=600)

    class CountedEngine:
        async def execute(self, **kwargs):
            if not first:
                raise RuntimeError("acceptance_second_agent_execution")
            store.incr(marker + ":agent-calls")
            store.expire(marker + ":agent-calls", 600)
            engine = select_agent_engine(Config(), user_id=owner)
            return await engine.execute(**kwargs)

    class ObservedCheckpoint(PreparedResultCoordinator):
        async def capture(self, **kwargs):
            await super().capture(**kwargs)
            execution = kwargs["execution_result"]
            save(":reply-digest", hashlib.sha256(kwargs["reply"].encode()).hexdigest())
            save(":model", str(execution.get("resolved_model") or ""))
            save(":tokens", int(execution.get("total_tokens") or 0))
            save(":receipts", len(execution.get("per_call_usage") or []))

    def hooks():
        original = original_factory()

        async def reserve(**kwargs):
            if not first:
                raise RuntimeError("acceptance_second_reservation")
            # Read-only budget preflight; the normal reservation/confirmation
            # implementation still owns the actual hold and its idempotency.
            estimate = await facade._estimate_reservation_credits(
                pg_connector=kwargs["pg_connector"],
                billing_cfg=facade._overlay_billing(kwargs["pg_connector"], kwargs["config"]),
                text=kwargs["text"],
                selected_model=kwargs["selected_model"],
                context_chars=kwargs["context_chars"],
                route="general",
            )
            if not 0 < estimate <= MAX_ESTIMATE:
                raise RuntimeError("acceptance_paid_budget_exceeded")
            result = await original.reserve_credits(**kwargs)
            if result[0] is None and (not result[1] or result[2] <= 0):
                raise RuntimeError("acceptance_paid_reservation_missing")
            return result

        async def charge(**kwargs):
            charged, metadata = await original.charge_and_describe(**kwargs)
            store.incr(marker + ":charge-calls")
            store.expire(marker + ":charge-calls", 600)
            if first and charged > 0:
                save(":first-debit", charged)
                save(":first-pid", os.getpid())
                # Actual BillingService transaction has committed. The job still
                # has its prepared checkpoint; no final messages/terminal commit.
                os._exit(73)
            if not first:
                save(":recovery-debit", charged)
            return charged, metadata

        return replace(
            original,
            prepared_results=ObservedCheckpoint(),
            reserve_credits=reserve,
            charge_and_describe=charge,
        )

    with patch.object(facade, "_execution_hooks", hooks):
        return await facade.process_agent_message_async(
            job_id=job_id,
            thread_id=thread_id,
            user_id=owner,
            text=REQUEST,
            selected_model=MODEL,
            route_override="general",
            planning=False,
            memory_enabled=False,
            session_data={"confirm_expensive_run": True},
            celery_task_id=task_id,
            agent_execution=CountedEngine(),
        )


def _value(store, key):
    value = store.get(key)
    return value.decode() if isinstance(value, bytes) else value


@celery_app.task(
    bind=True, name="s37.acceptance.paid-recovery", acks_late=True, reject_on_worker_lost=True
)
def recover_paid_result(self, *, marker, job_id, thread_id, owner):
    if not re.fullmatch(r"s37:celery-redelivery:[0-9a-f]{32}", marker):
        raise RuntimeError("acceptance_marker_invalid")
    if thread_id != str(UUID(marker.rsplit(":", 1)[1])):
        raise RuntimeError("acceptance_paid_fixture_invalid")
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 600)
    if attempt > 2:
        raise RuntimeError("acceptance_redelivery_limit")
    result = run_coroutine(
        _run_paid(
            marker=marker,
            job_id=job_id,
            thread_id=thread_id,
            owner=owner,
            first=attempt == 1,
            task_id=self.request.id,
        )
    )
    if attempt == 1:
        # A qualification/transport refusal must not masquerade as paid acceptance.
        return {"status": "no_paid_result", "attempts": 1}
    correct = (
        result.get("status") == "success"
        and hashlib.sha256(result.get("reply", "").encode()).hexdigest()
        == _value(store, marker + ":reply-digest")
        and _value(store, marker + ":model") == MODEL
        and int(_value(store, marker + ":tokens") or 0) > 0
        and int(_value(store, marker + ":receipts") or 0) > 0
        and int(_value(store, marker + ":agent-calls") or 0) == 1
        and int(_value(store, marker + ":charge-calls") or 0) == 2
        and int(_value(store, marker + ":recovery-debit") or 0) == 0
        and int((result.get("metadata", {}).get("usage") or {}).get("credits") or 0)
        == int(_value(store, marker + ":first-debit") or 0)
        and int(_value(store, marker + ":first-pid") or 0) != os.getpid()
    )
    if not correct:
        raise RuntimeError("acceptance_paid_resume_invalid")
    return {
        "status": "paid_recovered",
        "attempts": 2,
        "broker_redelivered": bool(self.request.delivery_info.get("redelivered")),
        "prefork_changed": True,
    }
