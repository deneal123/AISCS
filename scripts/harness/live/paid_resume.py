"""Verify redelivery of an already completed paid job, never another paid execution."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.environment import backend_http
from scripts.harness.live.paid import retire_test_runtime
from scripts.harness.live.paid_archive import archive_sources
from scripts.harness.live.paid_evidence import evidence
from scripts.harness.live.paid_setup import ANCHOR_JOB, paid_environment, paid_model
from scripts.harness.live.worker_process import deliver, prefork_worker

logging.disable(logging.CRITICAL)
STAGE = "paid_resume_environment"


async def require_no_paid_server():
    # This mode never starts an agents transport. A regression cannot silently
    # spend again: the worker's explicit HTTP sidecar address is unreachable.
    async with httpx.AsyncClient(timeout=3) as client:
        try:
            await client.get("http://agents:8091/health")
        except httpx.ConnectError:
            return
    raise AssertionError("paid_resume_requires_stopped_transport")


async def processing_jobs(container):
    async with container.infra.pg_connector.get_session_context() as db:
        return set(
            (
                await db.execute(
                    text(
                        "SELECT id FROM profile.user_launch "
                        "WHERE type='CHAT' AND status='PROCESSING'"
                    )
                )
            ).scalars()
        )


async def retained_job(container, job):
    from service.services.chat.domain.ide.runtime import RepositoryScope

    async with container.infra.pg_connector.get_session_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT t.*,j.status AS job_status,c.title,u.is_admin,u.is_active "
                        "FROM profile.harness_task t "
                        "JOIN profile.user_launch j ON j.id=t.task_id "
                        "JOIN profile.chat_threads c ON c.thread_id=t.thread_id "
                        "AND c.user_id=t.user_id "
                        'JOIN profile."user" u ON u.id=t.user_id '
                        "WHERE t.task_id=:job AND t.user_id="
                        "(SELECT user_id FROM profile.user_launch WHERE id=:anchor)"
                    ),
                    {"job": job, "anchor": ANCHOR_JOB},
                )
            )
            .mappings()
            .one()
        )
    assert row["title"] == "Harness: paid GigaChat acceptance"
    assert row["is_admin"] and row["is_active"]
    assert row["active_job_id"] == job and row["job_status"] == "SUCCESS"
    assert row["admission"]["surface"] == "ide"
    assert row["admission"]["pricing_model"] == paid_model()
    scope = RepositoryScope(row["thread_id"], row["user_id"], UUID(row["admission"]["project_id"]))
    return scope, {
        "job_id": str(job),
        "thread_id": str(scope.thread_id),
        "user_id": str(scope.user_id),
        "text": row["admission"]["goal"],
        "selected_model": row["admission"]["pricing_model"],
        "route_override": "general",
        "memory_enabled": False,
        "planning": False,
        "multi_intent": False,
        "session_data": {
            "confirm_expensive_run": True,
            "_ide_context": {
                "repository_id": str(scope.repository_id),
                "generation": row["admission"]["generation"],
            },
        },
    }


async def exercise(container, job):
    global STAGE
    from service.settings import config

    assert os.environ["CELERY__BROKER_URL"].startswith("redis://gpthub-harness-broker-")
    await require_no_paid_server()
    old_jobs = await processing_jobs(container)
    scope, kwargs = await retained_job(container, job)
    STAGE = "paid_resume_independent_receipts"
    first = await evidence(container, scope, job)
    queue = "harness-paid-resume-" + uuid4().hex
    STAGE = "paid_resume_duplicate_delivery"
    async with prefork_worker(config.pg.db, queue) as (app, first_pid):
        replay = await deliver(app, queue, kwargs)
        assert isinstance(replay, dict) and replay.get("status") == "success"
        assert await evidence(container, scope, job) == first
    STAGE = "paid_resume_worker_restart_redelivery"
    async with prefork_worker(config.pg.db, queue) as (app, second_pid):
        assert first_pid != second_pid
        replay = await deliver(app, queue, kwargs)
        assert isinstance(replay, dict) and replay.get("status") == "success"
        assert await evidence(container, scope, job) == first
    await require_no_paid_server()
    assert await processing_jobs(container) == old_jobs
    STAGE = "paid_resume_archive_and_retire_owned_runtime"
    await archive_sources(container, scope, job)
    await retire_test_runtime(container, scope)
    return {
        "paid_resume_verified": True,
        "job_id": str(job),
        "model": paid_model(),
        "credits": first["credits"],
        "tokens": first["tokens"],
        "rounds": first["rounds"],
        "commands": first["commands"],
        "charges": 1,
        "new_paid_calls": False,
        "redelivery_unchanged": True,
        "restart_redelivery_unchanged": True,
        "test_runtime_removed": True,
        "journal_and_snapshots_preserved": True,
    }


async def main(job):
    async with paid_environment() as container, backend_http(container):
        return await exercise(container, job)


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(UUID(sys.argv[-1])))))
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
