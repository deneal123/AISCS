"""Explicit isolated dev task; real audit/save, then actual prefork loss before delivery commit."""

import logging
import os
import re
import uuid

from sqlalchemy import text

from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.chat.application.documents.publication.service import deliver_one
from service.services.chat.infrastructure.chat_worker.factory import (
    ChatWorkerDependencyFactory,
    build_file_service,
)
from service.services.chat.infrastructure.chat_worker.task_runtime import run_coroutine
from service.settings import Config

logging.disable(logging.CRITICAL)


async def _deliver(publication_id, marker, first):
    config = Config()
    connector = PgConnector(config.pg)
    store = celery_app.backend.client
    factory = ChatWorkerDependencyFactory()
    redis = factory.create_redis_client(config)
    try:
        async with connector.get_session_context() as session:
            result = await session.execute(
                text(
                    'SELECT j.* FROM profile.document_publication_job j JOIN profile."user" u '
                    "ON u.id=j.user_id WHERE j.id=:id AND u.email=:email AND j.role='pdf' "
                    "AND j.billing_job_id=:marker"
                ),
                {
                    "id": uuid.UUID(publication_id),
                    "marker": marker,
                    "email": "s37-e2e-391e5206659a3654@example.com",
                },
            )
            row = dict(result.mappings().one())
            assert row["lease_token"] and row["status"] in {"pending_audit", "pending_delivery"}
            files = build_file_service(config, connector)

            class CrashAfterSavedFile:
                async def save_stream(self, *args, **kwargs):
                    saved = await files.save_stream(*args, **kwargs)
                    store.incr(marker + ":saves")
                    store.expire(marker + ":saves", 600)
                    if first:
                        assert not saved.reused
                        store.set(marker + ":file-id", str(saved.file_id), ex=600)
                        store.set(marker + ":first-pid", os.getpid(), ex=600)
                        # Actual storage and UserFile commit completed. Outbox and
                        # assistant attachment have not been changed to delivered.
                        os._exit(73)
                    old = store.get(marker + ":file-id")
                    old = old.decode() if isinstance(old, bytes) else old
                    assert saved.reused and str(saved.file_id) == old
                    return saved

            outcome = await deliver_one(
                config=config,
                pg_connector=connector,
                redis=redis,
                file_service=CrashAfterSavedFile(),
                session=session,
                row=row,
            )
            await session.commit()
            return outcome
    finally:
        await connector.close()
        redis.close()


@celery_app.task(
    bind=True,
    name="s37.acceptance.document-storage-crash",
    acks_late=True,
    reject_on_worker_lost=True,
)
def deliver_with_storage_crash(self, *, publication_id, marker):
    assert re.fullmatch(r"s37:document-storage:[0-9a-f]{32}", marker)
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 600)
    assert attempt <= 2
    outcome = run_coroutine(_deliver(publication_id, marker, attempt == 1))
    if attempt == 1:
        return {"status": "audit_or_delivery_unavailable", "attempts": 1}
    assert outcome == "delivered" and int(store.get(marker + ":saves") or 0) == 2
    assert int(store.get(marker + ":first-pid") or 0) != os.getpid()
    assert self.request.delivery_info.get("redelivered")
    return {"status": "delivered", "attempts": 2, "reused": True, "redelivered": True}
