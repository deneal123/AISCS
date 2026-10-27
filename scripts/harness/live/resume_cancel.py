"""Settle the retained stopped task from receipts, without repeating its effects."""

import asyncio
import json
import logging
import re
import sys
import traceback
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import text

from scripts.harness.live.environment import backend_http, cleanup_snapshots
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker

logging.disable(logging.CRITICAL)
STAGE = "resume_cancelled_environment"


async def records(container):
    async with container.infra.pg_connector.get_session_context() as db:
        task = (await db.execute(text("SELECT * FROM profile.harness_task"))).mappings().one()
        job = (await db.execute(text("SELECT * FROM profile.user_launch"))).mappings().one()
        operations = (
            (
                await db.execute(
                    text(
                        "SELECT operation_id,status,receipt,command FROM profile.harness_operation "
                        "ORDER BY operation_id"
                    )
                )
            )
            .mappings()
            .all()
        )
        return dict(task), dict(job), [dict(row) for row in operations]


async def exercise(container):
    global STAGE
    from service.services.chat.domain.ide.runtime import RepositoryScope
    from service.settings import config

    before, job, operations = await records(container)
    assert job["status"] == "PROCESSING" and job["payload"]["_cancel_requested_v1"] is True
    assert before["settled_credits"] == 0 and before["settlement"] is None
    commands = [item["command"] for item in operations if item["command"]]
    assert (
        len(commands) == 1
        and commands[0]["cleanup_confirmed"]
        and commands[0]["state"] == "cancelled"
    )
    scope = RepositoryScope(
        before["thread_id"], before["user_id"], UUID(commands[0]["repository_id"])
    )
    balance = await read_balance(container, scope)
    kwargs = {
        "job_id": str(job["id"]),
        "thread_id": str(before["thread_id"]),
        "user_id": str(before["user_id"]),
        "text": before["admission"]["goal"],
        "selected_model": before["admission"]["pricing_model"],
        "route_override": "general",
        "memory_enabled": False,
        "planning": False,
        "multi_intent": False,
        "session_data": {
            "confirm_expensive_run": True,
            "_ide_context": {
                "repository_id": before["admission"]["project_id"],
                "generation": before["admission"]["generation"],
            },
        },
    }
    STAGE = "receipt_only_cancelled_redelivery"
    queue = "harness-resume-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        result = await deliver(app, queue, kwargs)
        assert result["status"] == "success"
        assert result["metadata"]["task_result"]["status"] == "cancelled"
        after, stored, completed = await records(container)
        assert stored["status"] == "SUCCESS" and completed == operations
        assert after["settled_credits"] > 0 and after["checkpoint"] == before["checkpoint"]
        assert after["continuation"] == before["continuation"]
        assert balance - await read_balance(container, scope) == after["settled_credits"]
        async with container.infra.pg_connector.get_session_context() as db:
            assert await db.scalar(text("SELECT count(*) FROM profile.billing_events")) == 1
            assert (
                await db.scalar(text("SELECT sum(command_pins) FROM profile.ide_checkpoint_intent"))
                == 0
            )
            assert (
                await db.scalar(text("SELECT status FROM profile.token_reservations"))
                == "committed"
            )
    return {"cancelled_resume_verified": True, "new_effects": False, "charges": 1}


async def main(database):
    assert re.fullmatch(r"gpthub_acceptance_[a-f0-9]{24}", database)
    from service.settings import config

    config.pg.db = database
    config.agents.workspace_url = "http://workspace:8082"
    config.ide_checkpoints.enabled = True
    from service.composition.container import build_container
    from service.composition.state import set_current_container

    container = build_container(config)
    set_current_container(container)
    await container.infra.background_task_manager.start()
    try:
        async with backend_http(container):
            result = await exercise(container)
        await cleanup_snapshots(container)
    finally:
        await container.infra.background_task_manager.stop()
        await container.infra.pg_connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database="postgres",
    )
    try:
        await admin.execute('DROP DATABASE "' + database + '"')
    finally:
        await admin.close()
    return {**result, "fixture_data_removed": True}


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(sys.argv[-1]))))
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
