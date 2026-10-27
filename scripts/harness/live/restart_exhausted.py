"""Настоящее исчерпание доставки после commit записи, без повторных эффектов."""

import os
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.retry_barrier import operation_ids
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job


async def facts(container, job, *, before_dispatch=False):
    async with container.infra.pg_connector.get_session_context() as db:
        row = (
            (
                await db.execute(
                    text("SELECT status,payload FROM profile.user_launch WHERE id=:job"),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "SUCCESS"
        task = row["payload"]["metadata"]["task_result"]
        assert task["status"] == "blocked" and not task["verified"]
        assert task["blocker"] == "checkpoint_unavailable"
        if before_dispatch:
            assert not task["confirmed"] and not task["references"]
            assert task["unchecked"] == ["contract"]
            assert "_usage_journal_v1" not in row["payload"]
            assert await db.scalar(text("SELECT count(*) FROM profile.harness_grant")) == 0
        else:
            assert "script" in task["confirmed"] and "verify_project" in task["unchecked"]
        retry = row["payload"]["_harness_transport_retry_v1"]
        assert retry["count"] == 3 and retry["state"] == "blocked"
        assert await db.scalar(text("SELECT count(*) FROM profile.billing_events")) == 1
        if before_dispatch:
            # Один нулевой idempotency marker settlement, не фиктивный provider receipt.
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM profile.billing_events WHERE tokens=0 "
                        "AND (metadata->>'credits')::bigint=0 "
                        "AND (metadata->>'raw_cost_rub')::numeric=0"
                    )
                )
                == 1
            )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM profile.harness_grant "
                    "WHERE state NOT IN ('succeeded','waived')"
                )
            )
            == 0
        )
        assert await db.scalar(
            text(
                "SELECT count(*) FROM profile.harness_operation "
                "WHERE intent->>'name'='ide_write_file'"
            )
        ) == int(not before_dispatch)
        assert (
            await db.scalar(
                text("SELECT count(*) FROM profile.harness_operation WHERE command IS NOT NULL")
            )
            == 0
        )
        assert await db.scalar(text("SELECT status FROM profile.token_reservations")) == "committed"
        settled = await db.scalar(
            text("SELECT settled_credits FROM profile.harness_task WHERE task_id=:job"),
            {"job": job},
        )
    return task, settled


async def exercise(container, fault, restart_agents):
    from service.settings import config

    scope, job, balance, kwargs = await funded_job(container)
    before_dispatch = os.environ.get("HARNESS_ACCEPTANCE_RESTART_EXHAUSTED") == "before_dispatch"
    fault.job_id = str(job)
    queue = "harness-" + uuid4().hex
    before = {}
    async with httpx.AsyncClient(
        base_url="http://agents:8091",
        timeout=5,
        headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
    ) as client:

        async def interrupt():
            before["operations"] = await operation_ids(container, job)
            before["transport"] = (await client.get("/__harness_acceptance__/transport")).json()
            await restart_agents(client)

        if before_dispatch:
            before["operations"] = await operation_ids(container, job)
            before["transport"] = (await client.get("/__harness_acceptance__/transport")).json()
        else:
            fault.callback = interrupt
        async with prefork_worker(config.pg.db, queue) as (app, _pid):
            result = await deliver(app, queue, kwargs)
            assert fault.count == int(not before_dispatch), (
                "acceptance_committed_write_boundary_not_reached"
            )
            if fault.task:
                await fault.task
            assert result.get("status") == "success"
            task, settled = await facts(container, job, before_dispatch=before_dispatch)
            assert balance - await read_balance(container, scope) == settled
            assert settled == 0 if before_dispatch else settled > 0
            assert await operation_ids(container, job) == before["operations"]
            transport = (await client.get("/__harness_acceptance__/transport")).json()
            # OAuth при холодном запуске — не новый платный inference. Сравниваем
            # сами вызовы и инструменты плюс фактические journal operation IDs.
            assert {key: value for key, value in transport.items() if key != "oauth"} == {
                key: value for key, value in before["transport"].items() if key != "oauth"
            }
            observed = (await client.get("/__harness_acceptance__/runs")).json()
            assert observed and all(item["status"] == 503 for item in observed)
            replay = await deliver(app, queue, kwargs)
            assert replay["status"] == "success"
            assert await facts(container, job, before_dispatch=before_dispatch) == (task, settled)
            assert balance - await read_balance(container, scope) == settled
            assert await operation_ids(container, job) == before["operations"]
    return {
        "agents_restart_exhausted": True,
        "write_effects": int(not before_dispatch),
        "command_effects": 0,
        "charges": int(not before_dispatch),
    }
