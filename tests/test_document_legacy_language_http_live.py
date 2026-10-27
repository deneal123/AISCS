"""Explicit no-model dev HTTP regression for legacy publisher language support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from uuid import UUID, uuid4

import httpx
import pytest

from tests.test_document_checkpoint_http_live import _private_call
from tests.test_document_restart_live import _build

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("GPTHUB_DOCUMENT_LEGACY_HTTP_LIVE") != "1",
        reason="explicit isolated dev legacy document acceptance",
    ),
]


def _acceptance_token() -> str:
    # Read-only, fixed acceptance actor. Never print the token or use real users.
    probe = """
import asyncio,json,logging
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.models.key_value import UserTypes
from service.services.profile.application.auth_service import AuthService
logging.disable(logging.CRITICAL)
async def main():
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 try:
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   auth=AuthService(cfg.auth.model_copy(update={'jwt_exp_hours':1}),None,None,cfg.email)
   print(json.dumps({'token':auth._create_jwt(owner,None,UserTypes.REGISTERED)}))
 finally: await connector.close()
asyncio.run(main())
"""
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "acceptance_actor_unavailable"
    return json.loads(result.stdout)["token"]


@pytest.mark.parametrize("profile_id", ["ieee_journal", "aaai_conference"])
async def test_explicit_save_upgrades_legacy_preamble_and_builds_downloadable_pdf(profile_id):
    actor = uuid4().hex
    token = await asyncio.to_thread(_acceptance_token)
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        trust_env=False,
        cookies={"auth_token": token},
        headers={"X-Workspace-Session": actor},
        timeout=60,
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 legacy Cyrillic preview"})
        assert created.status_code == 201, "thread_create_failed"
        thread = str(UUID(created.json()["thread_id"]))
        base = f"/api/chats/{thread}"
        path = "documents/legacy-language"
        allocated = False
        renewal = None
        try:
            activated = await client.post(base + "/work/activate")
            assert activated.status_code == 200, "workspace_activate_failed"
            allocated = True
            revision = activated.json()["workspace"]["revision"]
            lease = await client.post(base + "/workspace/leases/acquire", json={"path": path})
            assert lease.status_code == 200, "project_lease_failed"
            fence = lease.json()["fence"]

            async def renew():
                while True:
                    await asyncio.sleep(10)
                    receipt = await client.post(
                        base + "/workspace/leases/renew", json={"path": path, "fence": fence}
                    )
                    assert receipt.status_code == 200, "lease_renewal_failed"

            renewal = asyncio.create_task(renew())
            project = await client.post(
                base + "/workspace/documents",
                json={
                    "path": path,
                    "profile_id": profile_id,
                    "mode": "draft",
                    "locale": "ru-RU",
                    "expected_revision": revision,
                    "fence": fence,
                },
            )
            assert project.status_code == 200, "project_create_failed"
            revision = project.json()["revision"]
            initial = await client.post(
                base + "/workspace/documents/authoring/edit",
                json={
                    "path": path,
                    "authoring_version": 0,
                    "draft_digest": None,
                    "expected_revision": revision,
                    "fence": fence,
                    "draft": {"title": "Русский черновик", "text": "Русский текст и English text."},
                },
            )
            assert initial.status_code == 200, "initial_semantic_save_failed"
            revision = initial.json()["revision"]
            source = await client.post(base + "/workspace/file", json={"path": path + "/main.tex"})
            assert source.status_code == 200
            current = source.json()["content"]
            assert r"\usepackage[T2A,T1]{fontenc}" in current
            legacy = current.replace("[T2A,T1]", "[T1]").replace(
                "\\usepackage[english,russian]{babel}\n", ""
            )
            file_lease = await client.post(
                base + "/workspace/leases/acquire", json={"path": path + "/main.tex"}
            )
            assert file_lease.status_code == 200
            downgraded = await client.post(
                base + "/workspace/write",
                json={
                    "path": path + "/main.tex",
                    "content": legacy,
                    "expected_revision": revision,
                    "fence": file_lease.json()["fence"],
                },
            )
            assert downgraded.status_code == 200, "legacy_fixture_write_failed"
            revision = downgraded.json()["revision"]
            failed = await client.post(
                base + "/workspace/documents/builds",
                json={
                    "path": path,
                    "expected_revision": revision,
                    "fence": fence,
                    "final": False,
                },
            )
            assert failed.status_code == 200, "legacy_build_start_failed"
            before = await _build(client, thread, failed.json()["build_id"])
            assert before["state"] == "failed", "legacy_fixture_did_not_reproduce"
            assert any(d["code"] == "unsupported_character" for d in before["diagnostics"])
            state = await client.post(base + "/workspace/documents/authoring", json={"path": path})
            assert state.status_code == 200, "legacy_authoring_unavailable"
            authoring = state.json()
            manifest_read = await client.post(
                base + "/workspace/file", json={"path": path + "/.gpthub-authoring.json"}
            )
            assert manifest_read.status_code == 200, "manifest_read_failed"
            manifest = json.loads(manifest_read.json()["content"])
            for relative in ["bibliography/references.bib", *manifest["block_files"]]:
                readable = await client.post(
                    base + "/workspace/file", json={"path": path + "/" + relative}
                )
                assert readable.status_code == 200, "managed_file_read_failed"
                assert not readable.json().get("truncated"), "managed_file_truncated"
            draft = authoring["draft"]
            draft["blocks"][0]["text"] = "Обновлённый русский текст и English text."
            payload = {
                "path": path,
                "draft": draft,
                "authoring_version": authoring["authoring_version"],
                "draft_digest": authoring["draft_digest"],
                "expected_revision": revision,
                "fence": fence,
            }
            saved = await client.post(base + "/workspace/documents/authoring/edit", json=payload)
            detail = saved.json().get("detail")
            code = (
                detail
                if isinstance(detail, str)
                and detail in {"authoring_invalid", "source_changed", "document_editor_unavailable"}
                else "other"
            )
            assert saved.status_code == 200, f"legacy_semantic_save_failed:{code}"
            revision = saved.json()["revision"]
            upgraded = await client.post(
                base + "/workspace/file", json={"path": path + "/main.tex"}
            )
            assert upgraded.status_code == 200
            assert r"\usepackage[T2A,T1]{fontenc}" in upgraded.json()["content"]
            assert r"\usepackage[english,russian]{babel}" in upgraded.json()["content"]
            stale = await client.post(base + "/workspace/documents/authoring/edit", json=payload)
            assert stale.status_code == 409, "stale_save_not_rejected"
            started = await client.post(
                base + "/workspace/documents/builds",
                json={
                    "path": path,
                    "expected_revision": revision,
                    "fence": fence,
                    "final": False,
                },
            )
            assert started.status_code == 200, "upgraded_build_start_failed"
            build_id = started.json()["build_id"]
            after = await _build(client, thread, build_id)
            assert after["state"] == "preview_ready", "upgraded_preview_not_ready"
            artifact = next(item for item in after["artifacts"] if item["role"] == "pdf")
            downloaded = await client.post(
                base
                + f"/workspace/documents/builds/{build_id}/artifacts/{artifact['artifact_id']}",
                json={},
            )
            assert downloaded.status_code == 200, "preview_download_failed"
            assert (
                downloaded.content.startswith(b"%PDF-") and b"%%EOF" in downloaded.content[-4096:]
            )
            assert hashlib.sha256(downloaded.content).hexdigest() == artifact["sha256"]
            assert not renewal.done(), "project_lease_renewal_stopped"
        finally:
            if renewal is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
            if allocated:
                assert (await _private_call(thread, actor, "__cleanup__", {}))[
                    "outcome"
                ] == "released"
            removed = await client.delete(base)
            assert removed.status_code in {200, 204}, "fixture_thread_cleanup_failed"
