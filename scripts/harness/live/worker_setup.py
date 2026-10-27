"""Create a funded disposable owner and NEW job; the real worker owns admission."""

import json
from uuid import uuid4

from sqlalchemy import text

from scripts.harness.live.command import prepare
from scripts.harness.live.worker_assertions import read_balance


async def funded_job(
    container,
    *,
    task_id=None,
    question=None,
    create_file=False,
    selected_model="GigaChat-3-Lightning",
):
    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        estimate_reservation_credits,
    )
    from service.settings import config

    question = question or "Create hello_world.py and verify that it prints hello world."
    estimate = await estimate_reservation_credits(
        pg_connector=container.infra.pg_connector,
        billing_cfg=config.billing,
        text=question,
        selected_model=selected_model,
        route="ide_harness",
    )
    scope, generation = await prepare(
        container, create_file=create_file, topup_credits=estimate + 10000
    )
    job = uuid4()
    async with container.infra.pg_connector.get_session_context() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload,celery_task_id) "
                "VALUES (:job,:owner,'CHAT','NEW',CAST(:body AS jsonb),:task)"
            ),
            {
                "job": job,
                "owner": scope.user_id,
                "body": json.dumps({"thread_id": str(scope.thread_id), "text": question}),
                "task": task_id,
            },
        )
        await db.commit()
    kwargs = {
        "job_id": str(job),
        "thread_id": str(scope.thread_id),
        "user_id": str(scope.user_id),
        "text": question,
        "selected_model": selected_model,
        "route_override": "general",
        "memory_enabled": False,
        "planning": False,
        "multi_intent": False,
        "session_data": {
            "confirm_expensive_run": True,
            "_ide_context": {"repository_id": str(scope.repository_id), "generation": generation},
        },
    }
    return scope, job, await read_balance(container, scope), kwargs
