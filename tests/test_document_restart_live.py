"""Explicit no-LLM dev-sidecar restart acceptance via authenticated Work routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from uuid import UUID, uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_DOCUMENT_RESTART") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit dev sidecar restart acceptance",
    ),
]


def _health():
    result = subprocess.run(
        [
            "docker",
            "exec",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            "import json,urllib.request; "
            "h=json.load(urllib.request.urlopen('http://workspace:8080/health',timeout=5)); "
            "print(json.dumps(h.get('documents',{})))",
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    return json.loads(result.stdout) if result.returncode == 0 else None


def _cleanup_workspace(thread_id):
    """Privately resolve only the still-owned, exact acceptance thread."""
    probe = """
import asyncio,json,logging,sys,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.cache.manager import RedisManager
from service.infrastructure.workspace_client import read_binding_state,release_workspace
async def main():
 cfg=Config(); db=PgConnector(cfg.pg); manager=RedisManager(cfg.redis)
 thread=str(uuid.UUID(json.load(sys.stdin)['thread_id']))
 try:
  async with db.get_session_context() as session:
   row=(await session.execute(text('SELECT t.user_id FROM profile.chat_threads t '
    'JOIN profile."user" u ON u.id=t.user_id WHERE t.thread_id=:thread '
    'AND t.title=:title AND u.email=:email'), {'thread':uuid.UUID(thread),
    'title':'S37 preview recovery','email':'s38-video-acceptance@example.com'})).first()
   assert row is not None
  redis=manager.get_client(); state,ref=await read_binding_state(redis,thread)
  assert state=='absent' or state=='ready' and str(ref['user_id'])==str(row[0])
  assert await release_workspace(redis,thread)
  assert (await read_binding_state(redis,thread))[0]=='absent'
  print(json.dumps({'workspace_cleaned':True}))
 finally:
  await manager.close(); await db.close()
asyncio.run(main())
"""
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", probe],
        input=json.dumps({"thread_id": str(UUID(thread_id))}).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "fixture_workspace_cleanup_unconfirmed"
    assert json.loads(result.stdout) == {"workspace_cleaned": True}


async def _build(client, thread_id, build_id):
    async with asyncio.timeout(120):
        while True:
            response = await client.post(
                f"/api/chats/{thread_id}/workspace/documents/builds/{build_id}", json={}
            )
            assert response.status_code == 200, "build_status_unavailable"
            status = response.json()
            if status.get("state") in {"preview_ready", "failed", "cancelled"}:
                return status
            await asyncio.sleep(1)


async def test_preview_survives_real_sidecar_restart_with_same_artifact_digest():
    health = await asyncio.to_thread(_health)
    assert health is not None and health.get("active") == 0, "active_builds_prevent_restart"
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        headers={"X-Workspace-Session": str(uuid4())},
        timeout=60,
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 preview recovery"})
        assert created.status_code == 201, "thread_create_failed"
        thread_id = str(UUID(created.json()["thread_id"]))
        try:
            passive = await client.get(f"/api/chats/{thread_id}/work")
            assert passive.status_code == 200 and passive.json()["workspace"]["state"] == "absent"
            activated = await client.post(f"/api/chats/{thread_id}/work/activate")
            assert activated.status_code == 200, "workspace_activate_failed"
            revision = activated.json()["workspace"]["revision"]
            path = "documents/recovery-preview"
            acquired = await client.post(
                f"/api/chats/{thread_id}/workspace/leases/acquire", json={"path": path}
            )
            assert acquired.status_code == 200, "project_lease_failed"
            fence = acquired.json()["fence"]
            project = await client.post(
                f"/api/chats/{thread_id}/workspace/documents",
                json={
                    "path": path,
                    "profile_id": "generic_document",
                    "mode": "draft",
                    "expected_revision": revision,
                    "fence": fence,
                },
            )
            assert project.status_code == 200, "project_scaffold_failed"
            revision = project.json()["revision"]
            started = await client.post(
                f"/api/chats/{thread_id}/workspace/documents/builds",
                json={"path": path, "expected_revision": revision, "fence": fence, "final": False},
            )
            assert started.status_code == 200, "preview_start_failed"
            build_id = started.json()["build_id"]
            before = await _build(client, thread_id, build_id)
            assert before["state"] == "preview_ready", "preview_not_ready"
            artifact = next(row for row in before["artifacts"] if row["role"] == "pdf")
            download_path = (
                f"/api/chats/{thread_id}/workspace/documents/builds/{build_id}"
                f"/artifacts/{artifact['artifact_id']}"
            )
            pdf = await client.post(download_path, json={})
            assert pdf.status_code == 200
            digest = hashlib.sha256(pdf.content).hexdigest()
            assert digest == artifact["sha256"]
            health = await asyncio.to_thread(_health)
            assert health is not None and health.get("active") == 0
            restarted = await asyncio.to_thread(
                subprocess.run,
                ["docker", "restart", "gpthub-dev-workspace-1"],
                capture_output=True,
                timeout=60,
                check=False,
            )
            assert restarted.returncode == 0, "sidecar_restart_failed"
            async with asyncio.timeout(60):
                while await asyncio.to_thread(_health) is None:
                    await asyncio.sleep(1)
            after = await _build(client, thread_id, build_id)
            assert after["state"] == "preview_ready"
            assert after["source_revision"] == before["source_revision"]
            assert after["artifacts"] == before["artifacts"]
            restored_pdf = await client.post(download_path, json={})
            assert restored_pdf.status_code == 200
            assert hashlib.sha256(restored_pdf.content).hexdigest() == digest
            health = await asyncio.to_thread(_health)
            assert health is not None and health.get("recovered", 0) >= 1
            work = await client.get(f"/api/chats/{thread_id}/work")
            assert work.status_code == 200 and work.json()["workspace"]["state"] == "ready"
            # A second, owned build exercises crash recovery rather than a
            # graceful shutdown. Refuse to interrupt other active builds.
            health = await asyncio.to_thread(_health)
            assert health is not None and health.get("active") == 0
            acquired = await client.post(
                f"/api/chats/{thread_id}/workspace/leases/acquire", json={"path": path}
            )
            assert acquired.status_code == 200
            started = await client.post(
                f"/api/chats/{thread_id}/workspace/documents/builds",
                json={
                    "path": path,
                    "expected_revision": work.json()["workspace"]["revision"],
                    "fence": acquired.json()["fence"],
                    "final": False,
                },
            )
            assert started.status_code == 200 and started.json()["state"] == "building"
            interrupted_id = started.json()["build_id"]
            killed = await asyncio.to_thread(
                subprocess.run,
                ["docker", "kill", "--signal=KILL", "gpthub-dev-workspace-1"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            try:
                assert killed.returncode == 0, "sidecar_crash_failed"
            finally:
                resumed = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "start", "gpthub-dev-workspace-1"],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                assert resumed.returncode == 0, "sidecar_resume_failed"
            async with asyncio.timeout(60):
                while await asyncio.to_thread(_health) is None:
                    await asyncio.sleep(1)
            interrupted = await _build(client, thread_id, interrupted_id)
            assert interrupted["state"] == "failed"
            assert interrupted["failure_code"] == "build_interrupted"
            assert not interrupted.get("artifacts"), "interrupted_build_published_partial_artifact"
            health = await asyncio.to_thread(_health)
            assert health is not None and health.get("compiler_cleanup", 0) >= 1
            orphan = await asyncio.to_thread(
                subprocess.run,
                ["docker", "ps", "-aq", "--filter", f"name=^/gpthub-doc-{interrupted_id}$"],
                capture_output=True,
                timeout=15,
                check=False,
            )
            assert orphan.returncode == 0 and not orphan.stdout.strip(), "compiler_orphan_retained"
            restored_pdf = await client.post(download_path, json={})
            assert restored_pdf.status_code == 200
            assert hashlib.sha256(restored_pdf.content).hexdigest() == digest
        finally:
            await asyncio.to_thread(_cleanup_workspace, thread_id)
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
