"""Барьер настоящей очереди: повтор опубликован, но следующий dispatch ещё невозможен."""

import asyncio

import httpx
from sqlalchemy import text


async def consumer(app, queue, *, enabled):
    operation = app.control.add_consumer if enabled else app.control.cancel_consumer
    replies = await asyncio.to_thread(
        operation, queue, destination=[queue + "@acceptance"], reply=True, timeout=10
    )
    assert replies and all("ok" in body for reply in replies for body in reply.values())


async def operation_ids(container, job):
    async with container.infra.pg_connector.get_session_context() as db:
        return {
            table: tuple(
                str(item)
                for item in await db.scalars(
                    text(
                        "SELECT operation_id FROM profile."
                        + table
                        + " WHERE task_id=:job ORDER BY operation_id"
                    ),
                    {"job": job},
                )
            )
            for table in ("harness_grant", "harness_operation")
        }


async def stop_pending(container, job, task_id, token, app, queue, agents):
    async with asyncio.timeout(50):
        while True:
            async with container.infra.pg_connector.get_session_context() as db:
                intent = await db.scalar(
                    text(
                        "SELECT payload->'_harness_transport_retry_v1' "
                        "FROM profile.user_launch WHERE id=:job"
                    ),
                    {"job": job},
                )
            if intent and intent["state"] == "pending":
                break
            await asyncio.sleep(0.05)
        before = {
            "transport": (await agents.get("/__harness_acceptance__/transport")).json(),
            "operations": await operation_ids(container, job),
            "retry": intent,
        }
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8002", timeout=5, cookies={"auth_token": token}
        ) as client:
            response = await client.post("/api/jobs/v1/task/" + task_id + "/cancel")
            assert response.status_code == 200 and response.json()["cancelled"] is True
        # Намерение уже committed; очередь могла ещё не получить сообщение retry.
        # Это не важно: consumer открыт только после подтверждённого Stop.
        await consumer(app, queue, enabled=True)
        return before
