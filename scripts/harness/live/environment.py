"""Full migrated PostgreSQL and real storage, private to one acceptance process."""

import asyncio
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import asyncpg
import uvicorn


async def initialize_database(database):
    from service.settings import config

    metadata = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database=database,
        timeout=5,
    )
    try:
        await metadata.execute("CREATE TABLE alembic_version (version_num varchar(255) NOT NULL)")
    finally:
        await metadata.close()
    migration = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("migrate.py")),
        env={**os.environ, "PG__DB": database},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    async with asyncio.timeout(90):
        output, _ = await migration.communicate()
        if migration.returncode:
            print(output.decode("utf-8"))
            raise RuntimeError("acceptance_migration_failed")


@asynccontextmanager
async def environment(*, existing_database=None):
    from service.settings import config

    marker = uuid4().hex[:24]
    database = existing_database or "gpthub_acceptance_" + marker
    assert re.fullmatch(r"gpthub_acceptance_[a-f0-9]{24}", database)
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database=config.pg.db,
        timeout=5,
    )
    container = None
    succeeded = False
    if existing_database is None:
        await admin.execute('CREATE DATABASE "' + database + '"')
    try:
        if existing_database is None:
            await initialize_database(database)
        # This process only: no permanent dev flag/config changes.
        config.pg.db = database
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
        await container.infra.pg_connector.verify_connection()
        await container.infra.background_task_manager.start()
        yield container
        succeeded = True
    finally:
        if container:
            await container.infra.background_task_manager.stop()
            if succeeded:
                await cleanup_snapshots(container)
            await container.infra.pg_connector.close()
            if container.infra.redis_manager:
                await container.infra.redis_manager.close()
        if succeeded:
            await admin.execute('DROP DATABASE "' + database + '" WITH (FORCE)')
        else:
            # Keep authority/receipts for reconciliation, especially after lost ACK.
            print(f'{{"retained_database":"{database}"}}')
        await admin.close()


async def cleanup_snapshots(container):
    from sqlalchemy import text

    from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob
    from service.services.chat.domain.ide.runtime import RepositoryScope

    async with container.infra.pg_connector.get_session_context() as db:
        rows = (await db.execute(text("SELECT * FROM profile.ide_checkpoint_intent"))).mappings()
        for row in rows:
            assert row["storage_namespace"] == container.infra.storage.namespace_id
            scope = RepositoryScope(row["thread_id"], row["user_id"], row["repository_id"])
            blob = CheckpointBlob(scope, row["checkpoint_id"], row["sha256"], row["size"])
            await container.infra.storage.delete_file(file_key=blob.key_for(scope))


@asynccontextmanager
async def backend_http(container, *, crash=None):
    from scripts.harness.live.diagnostics import PermitDiagnostics, observe_command_failures
    from scripts.harness.live.lost_ack import LostAck, LostAckMiddleware
    from service.main import create_app

    @asynccontextmanager
    async def owned_lifespan(_app):
        # Global maintenance/queue processors must not touch another dev job.
        # Application handlers, repositories, storage and callback routes are real.
        yield

    app = create_app(container_override=container)
    if crash is not None:
        from scripts.harness.live.crash_boundary import CrashBoundaryMiddleware

        app.add_middleware(CrashBoundaryMiddleware, fault=crash)
    fault = LostAck(os.environ.get("HARNESS_ACCEPTANCE_LOST_ACK", ""))
    if fault.mode in {"paid_receipt_unavailable", "stream_receipt_unavailable"}:
        from scripts.harness.live.receipt_unavailable import ReceiptUnavailableMiddleware

        app.add_middleware(ReceiptUnavailableMiddleware, fault=fault)
    else:
        app.add_middleware(LostAckMiddleware, fault=fault)
    observe_command_failures()
    app.add_middleware(PermitDiagnostics)
    app.router.lifespan_context = owned_lifespan
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8002,
            access_log=False,
            log_level="critical",
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(30):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("acceptance_backend_not_started")
                await asyncio.sleep(0.05)
        yield fault
    finally:
        server.should_exit = True
        async with asyncio.timeout(15):
            await task
