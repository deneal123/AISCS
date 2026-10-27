"""Existing dev admin, new owned project, ordinary worker admission and money."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import text

from scripts.harness.live.worker_assertions import read_balance

ANCHOR_JOB = UUID("143f2048-0ee9-40e5-92dc-50c3a977e6d6")
QUESTION = (
    "Создай hello_world.py в корне репозитория. Он должен вывести ровно hello world "
    "и перевод строки. Действительно запусти скрипт и проверь точный вывод. "
    "Не устанавливай зависимости. Заверши только после проверки актуального файла."
)


def paid_model():
    model = os.environ.get("HARNESS_ACCEPTANCE_PAID_MODEL", "GigaChat-3-Lightning")
    assert model in {"GigaChat-3-Lightning", "GigaChat-2-Max"}
    return model


@asynccontextmanager
async def paid_environment():
    from service.settings import config

    assert not config.pg.db.startswith("gpthub_acceptance_")
    config.agents.workspace_url = "http://workspace:8082"
    config.agents.sidecar_url = "http://agents:8091"
    config.ide_checkpoints.enabled = True
    os.environ.update(HARNESS__IDE_ENABLED="true", HARNESS__IDE_COMMANDS_ENABLED="true")
    from service.composition.container import build_container
    from service.composition.state import set_current_container
    from service.services.chat.application.harness_capability import settings

    settings.cache_clear()
    container = build_container(config)
    set_current_container(container)
    try:
        async with container.infra.pg_connector.get_session_context() as db:
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "048_retained_expiry"
            )
        await container.infra.background_task_manager.start()
        yield container
    finally:
        await container.infra.background_task_manager.stop()
        await container.infra.pg_connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()


async def prepare_paid_project(container):
    from service.composition.ide import build_ide_runtime
    from service.services.chat.application.ide.prepare import IdePrepareService
    from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag
    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        estimate_reservation_credits,
    )
    from service.services.chat.persistence.chat_repository import ChatRepository
    from service.settings import config

    connector = container.infra.pg_connector
    async with connector.get_session_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT j.user_id,u.is_admin,u.is_active FROM profile.user_launch j "
                        'JOIN profile."user" u ON u.id=j.user_id WHERE j.id=:job'
                    ),
                    {"job": ANCHOR_JOB},
                )
            )
            .mappings()
            .one()
        )
        assert row["is_admin"] and row["is_active"]
    actor, thread = row["user_id"], uuid4()
    estimate = await estimate_reservation_credits(
        pg_connector=connector,
        billing_cfg=config.billing,
        text=QUESTION,
        selected_model=paid_model(),
        route="ide_harness",
    )
    # Operator ceiling, not a replacement for backend grant/reservation checks.
    assert 0 < estimate <= (50000 if paid_model() == "GigaChat-3-Lightning" else 700000)
    await ChatRepository(connector).create_thread(
        actor, "Harness: платная приёмка GigaChat", str(thread)
    )
    runtime = build_ide_runtime(connector)
    prepared = await IdePrepareService(runtime, container.infra.redis_client).prepare(
        thread_id=thread,
        user_id=actor,
        session="harness-paid-acceptance",
    )
    scope = RepositoryScope(thread, actor, UUID(prepared["repository"]["repository_id"]))
    async with asyncio.timeout(30):
        while prepared["runtime"]["workspace"]["state"] != "ready":
            await asyncio.sleep(0.1)
            prepared["runtime"] = await runtime.status(scope)
    resolved = await runtime.resolve(scope)
    before = await read_balance(container, scope)
    assert before >= estimate
    return scope, generation_tag(resolved.attempt), before, estimate


async def new_paid_job(container, scope, generation):
    job, task = uuid4(), uuid4()
    async with container.infra.pg_connector.get_session_context() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload,celery_task_id) "
                "VALUES (:job,:owner,'CHAT','NEW',CAST(:body AS jsonb),:task)"
            ),
            {
                "job": job,
                "owner": scope.user_id,
                "task": str(task),
                "body": json.dumps({"thread_id": str(scope.thread_id)}),
            },
        )
        await db.commit()
    return (
        job,
        str(task),
        {
            "job_id": str(job),
            "thread_id": str(scope.thread_id),
            "user_id": str(scope.user_id),
            "text": QUESTION,
            "selected_model": paid_model(),
            "route_override": "general",
            "memory_enabled": False,
            "planning": False,
            "multi_intent": False,
            "session_data": {
                "confirm_expensive_run": True,
                "_ide_context": {
                    "repository_id": str(scope.repository_id),
                    "generation": generation,
                },
            },
        },
    )
