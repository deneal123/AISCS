"""Observe and Stop a retained fixture operation; never call execute again."""

import asyncio
import json
import logging
import re
import sys
import traceback

import asyncpg
import httpx
from sqlalchemy import text

from scripts.harness.live.environment import backend_http, cleanup_snapshots

logging.disable(logging.CRITICAL)


async def main(database):
    from service.settings import config

    assert re.fullmatch(r"gpthub_acceptance_[a-f0-9]{24}", database)
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database=config.pg.db,
    )
    config.pg.db = database
    config.agents.workspace_url = "http://workspace:8082"
    config.ide_checkpoints.enabled = True

    from service.composition.container import build_container
    from service.composition.state import set_current_container
    from service.services.chat.application.harness_capability import HarnessOwner, issue
    from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository

    container = build_container(config)
    set_current_container(container)
    connector = container.infra.pg_connector
    await container.infra.background_task_manager.start()
    try:
        async with connector.get_session_context() as db:
            row = (await db.execute(text("SELECT * FROM profile.harness_task"))).mappings().one()
            operations = (
                (
                    await db.execute(
                        text(
                            "SELECT operation_id,command FROM "
                            "profile.harness_operation WHERE command IS NOT NULL"
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(operations) == 1
        owner = HarnessOwner(
            task_id=str(row["task_id"]),
            job_id=str(row["active_job_id"]),
            user_id=str(row["user_id"]),
            thread_id=str(row["thread_id"]),
            attempt_id=str(row["execution_attempt_id"]),
            epoch=row["fencing_epoch"],
            project_id=row["admission"]["project_id"],
            generation=row["admission"]["generation"],
        )
        operation = operations[0]
        assert operation["command"]["state"] == "unknown"
        assert operation["command"]["dispatch_authorized"] is False
        async with (
            backend_http(container),
            httpx.AsyncClient(
                base_url="http://127.0.0.1:8002",
                timeout=60,
                headers={"Authorization": "Bearer " + issue(owner)},
            ) as client,
        ):
            response = await client.post(
                "/internal/harness/v1/commands",
                json={"action": "stop", "operation_id": str(operation["operation_id"])},
            )
            assert response.status_code == 200
            result = response.json()
            async with asyncio.timeout(30):
                while result["command"]["state"] not in {"cancelled", "failed", "completed"}:
                    await asyncio.sleep(0.1)
                    response = await client.post(
                        "/internal/harness/v1/commands",
                        json={"action": "status", "operation_id": str(operation["operation_id"])},
                    )
                    assert response.status_code == 200
                    result = response.json()
            record = await IdeCommandRepository(connector).command_status(
                owner, operation["operation_id"]
            )
            assert record.cleanup_confirmed and record.state == "cancelled"
            assert not record.dispatch_authorized
        await cleanup_snapshots(container)
    finally:
        await container.infra.background_task_manager.stop()
        await connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()
        await admin.close()
    # No active process/effect remains; delete only the explicit fixture database.
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database="postgres",
    )
    await admin.execute('DROP DATABASE "' + database + '" WITH (FORCE)')
    await admin.close()
    return {"reconciled_stop": True, "command_repeated": False, "fixture_data_removed": True}


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(sys.argv[-1]))))
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": "reconcile_stop",
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
