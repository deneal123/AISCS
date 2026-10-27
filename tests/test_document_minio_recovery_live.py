"""Explicit metered dev outage test; always bring MinIO back before cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_MINIO_RECOVERY") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit local storage outage and metered vision acceptance",
    ),
]


async def _docker(*args, input_bytes=None):
    return await asyncio.to_thread(
        subprocess.run,
        ["docker", *args],
        input=input_bytes,
        capture_output=True,
        timeout=90,
        check=False,
    )


async def _snapshot(thread_id=""):
    probe = """
import asyncio,json,logging,sys
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
logging.disable(logging.CRITICAL)
async def main():
 try:
  config=Config()
  async with PgConnector(config.pg).get_session_context() as session:
   if not sys.argv[1]:
    count=await session.scalar(text('''SELECT count(*)
     FROM profile.document_publication_job WHERE status IN ('pending_audit','pending_delivery')'''))
    print(json.dumps({'pending':count,'local_storage_target':
     config.storage.backend=='minio' and config.minio.endpoint in
      {'minio:9000','gpthub-dev-minio-1:9000'}})); return
   result=await session.execute(text('''
    SELECT j.status,j.attempts,j.failure_code,j.user_file_id,j.role,j.artifact_sha256,
     (SELECT count(*) FROM profile.user_file f
       WHERE f.user_id=j.user_id AND f.id=j.user_file_id) AS files,
     (SELECT count(*) FROM profile.billing_events e WHERE e.user_id=j.user_id
       AND e.event_type='usage' AND e.metadata->>'idempotency_key'=j.billing_job_id) AS charges
    FROM profile.document_publication_job j
    JOIN profile."user" u ON u.id=j.user_id
    WHERE j.thread_id=:thread AND u.email=:email ORDER BY j.role
   '''),{'thread':sys.argv[1],'email':'s37-e2e-391e5206659a3654@example.com'})
   print(json.dumps([dict(r,user_file_id=str(r['user_file_id']) if r['user_file_id'] else None)
    for r in result.mappings()]))
 except Exception:
  print('{}'); raise SystemExit(1)
asyncio.run(main())
"""
    result = await _docker(
        "exec",
        "-i",
        "gpthub-dev-backend-1",
        "python",
        "-",
        thread_id,
        input_bytes=probe.encode(),
    )
    assert result.returncode == 0, "publication_snapshot_failed"
    return json.loads(result.stdout)


async def _restore_minio():
    result = await _docker("start", "gpthub-dev-minio-1")
    assert result.returncode == 0, "minio_restore_failed"
    async with asyncio.timeout(60):
        while True:
            health = await _docker(
                "inspect", "--format", "{{.State.Health.Status}}", "gpthub-dev-minio-1"
            )
            if health.returncode == 0 and health.stdout.strip() == b"healthy":
                return
            await asyncio.sleep(1)


async def _delivery_round():
    # Existing task path, not DB edits, backoff bypass or fault-injection code.
    probe = """
import json,logging
logging.disable(logging.CRITICAL)
try:
 from service.infrastructure.messaging.celery_app import celery_app
 job=celery_app.send_task('service.infrastructure.messaging.tasks.deliver_document_publications')
 result=job.get(timeout=60)
 print(json.dumps({'claimed':int(result.get('claimed',0)),
  'delivered':int(result.get('delivered',0))}))
except Exception:
 print('{}'); raise SystemExit(1)
"""
    result = await _docker(
        "exec", "-i", "gpthub-dev-backend-1", "python", "-", input_bytes=probe.encode()
    )
    assert result.returncode == 0, "delivery_worker_round_failed"
    return json.loads(result.stdout)


async def test_minio_outage_defers_then_delivers_without_duplicate_file_or_charge():
    preflight = await _snapshot()
    assert preflight["local_storage_target"], "local_minio_not_actual_storage_target"
    for worker in ("gpthub-dev-celery-worker-agents-1", "gpthub-dev-celery-worker-maintenance-1"):
        result = await _docker(
            "exec",
            worker,
            "python",
            "-c",
            "from service.settings import Config; c=Config(); "
            "print(int(c.storage.backend=='minio' and c.minio.endpoint in "
            "{'minio:9000','gpthub-dev-minio-1:9000'}))",
        )
        assert result.returncode == 0 and result.stdout.strip() == b"1", (
            "worker_storage_target_mismatch"
        )
    assert preflight["pending"] == 0, "other_pending_publications_prevent_outage"
    token = os.environ["E2E_AUTH_TOKEN"]
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=60
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 storage recovery"})
        assert created.status_code == 201
        thread_id = str(UUID(created.json()["thread_id"]))
        storage_stopped = False
        try:
            # Mark first so even a failed/uncertain stop triggers restoration.
            storage_stopped = True
            stopped = await _docker("stop", "--time=1", "gpthub-dev-minio-1")
            assert stopped.returncode == 0, "minio_stop_failed"
            async with (
                connect(
                    f"ws://localhost:8001/api/chats/{thread_id}/ws",
                    additional_headers={"Cookie": f"auth_token={token}"},
                    max_size=2_000_000,
                ) as socket,
                asyncio.timeout(180),
            ):
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "id": str(uuid4()),
                            "text": 'Создай PDF и напиши "тест"',
                            "model": "GigaChat-2",
                            "route_override": "pdf_gen",
                            "memory_enabled": False,
                        },
                        ensure_ascii=False,
                    )
                )
                job_id = None
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") in {"claimed", "replay"}:
                        event = event.get("data") or {}
                    assert event.get("type") != "error", "outage_run_failed"
                    if event.get("type") == "job_created":
                        job_id = event.get("job_id")
                    if event.get("type") == "agent_reply" and event.get("job_id") == job_id:
                        metadata = event.get("metadata") or {}
                        assert metadata.get("document_outcome") in {"completed", "deferred"}
                        assert not metadata.get("generated_files"), (
                            "phantom_library_card_during_outage"
                        )
                        break
            async with asyncio.timeout(180):
                while True:
                    rows = await _snapshot(thread_id)
                    pdf = next((row for row in rows if row["role"] == "pdf"), None)
                    if pdf and pdf["attempts"] >= 1:
                        break
                    await asyncio.sleep(2)
            assert pdf["status"] == "pending_delivery"
            assert pdf["failure_code"] == "unavailable"
            assert pdf["files"] == 0 and pdf["user_file_id"] is None
            assert pdf["charges"] == 1, "initial_charge_missing_or_duplicated"
            await _restore_minio()
            storage_stopped = False
            async with asyncio.timeout(240):
                while True:
                    rows = await _snapshot(thread_id)
                    if rows and all(row["status"] == "delivered" for row in rows):
                        break
                    await asyncio.sleep(3)
            assert len({row["role"] for row in rows}) == len(rows)
            pdf = next(row for row in rows if row["role"] == "pdf")
            assert pdf["files"] == 1 and pdf["charges"] == 1
            response = await client.get(
                f"/api/service/files/v1/{pdf['user_file_id']}/download", follow_redirects=True
            )
            assert response.status_code == 200 and response.content.startswith(b"%PDF-")
            assert hashlib.sha256(response.content).hexdigest() == pdf["artifact_sha256"]
            history = await client.get(f"/api/chats/{thread_id}")
            assert history.status_code == 200
            files = [
                item
                for row in history.json()["messages"]
                for item in (row.get("metadata") or {}).get("generated_files") or []
            ]
            assert sum(item.get("file_id") == pdf["user_file_id"] for item in files) == 1
            repeated = await _delivery_round()
            assert repeated["claimed"] == 0, "delivered_jobs_reclaimed"
            assert await _snapshot(thread_id) == rows, "delivery_replay_changed_files_or_charge"
        finally:
            if storage_stopped:
                await _restore_minio()
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
