"""Opt-in metered Chat -> audited PDF -> durable Library delivery acceptance."""

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
        os.getenv("S37_LIVE_LITERAL_DELIVERY") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit metered local PDF delivery acceptance",
    ),
]


def _inspect_pdf(payload: bytes, expected: str) -> None:
    # All inspection stays in a disposable offline compiler container. No
    # filenames, URLs, PDF contents or raw command output are printed on failure.
    probe = """
import json,pathlib,subprocess,sys
p=pathlib.Path('/tmp/check.pdf'); p.write_bytes(sys.stdin.buffer.read())
valid=subprocess.run(['qpdf','--check',str(p)],capture_output=True).returncode==0
info=subprocess.run(['pdfinfo',str(p)],capture_output=True)
text=subprocess.run(['pdftotext','-layout',str(p),'-'],capture_output=True)
print(json.dumps({'valid':valid,'info':info.returncode==0,
 'text':text.stdout.decode('utf-8').strip(),'extracted':text.returncode==0}))
"""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,size=33554432,mode=1777",
            "--entrypoint=python3",
            "gpthub-document-runtime:latest",
            "-c",
            probe,
        ],
        input=payload,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "pdf_inspector_failed"
    report = json.loads(result.stdout)
    assert report["valid"] and report["info"] and report["extracted"], "pdf_validation_failed"
    assert report["text"] == expected, "literal_pdf_content_mismatch"


async def test_two_literal_pdfs_are_audited_delivered_and_downloadable():
    token = os.environ["E2E_AUTH_TOKEN"]
    model = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-2")
    digests: list[str] = []
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=60
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 literal delivery"})
        assert created.status_code == 201, "thread_create_failed"
        thread_id = str(UUID(created.json()["thread_id"]))
        try:
            for literal in ("тест", "тест 2"):
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
                                "text": f'Создай PDF и напиши "{literal}"',
                                "model": model,
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
                        assert event.get("type") != "error", "literal_run_failed"
                        if event.get("type") == "job_created":
                            job_id = event.get("job_id")
                        if event.get("type") == "agent_reply" and event.get("job_id") == job_id:
                            metadata = event.get("metadata") or {}
                            assert metadata.get("document_outcome") in {"completed", "deferred"}, (
                                "literal_document_not_publishable"
                            )
                            assert metadata.get("requested_authoring_model") == model
                            assert metadata.get("actual_authoring_model") == model
                            break
                async with asyncio.timeout(180):
                    while True:
                        history = await client.get(f"/api/chats/{thread_id}")
                        assert history.status_code == 200, "history_unavailable"
                        messages = history.json()["messages"]
                        assistant = next(
                            (row for row in reversed(messages) if row.get("sender") == "assistant"),
                            None,
                        )
                        files = ((assistant or {}).get("metadata") or {}).get(
                            "generated_files"
                        ) or []
                        pdf = next(
                            (row for row in files if row.get("mime_type") == "application/pdf"),
                            None,
                        )
                        if pdf:
                            break
                        await asyncio.sleep(2)
                file_id = str(UUID(pdf["file_id"]))
                response = await client.get(
                    f"/api/service/files/v1/{file_id}/download", follow_redirects=True
                )
                assert response.status_code == 200, "library_download_failed"
                payload = response.content
                assert 1_000 < len(payload) < 10_000_000 and payload.startswith(b"%PDF-")
                await asyncio.to_thread(_inspect_pdf, payload, literal)
                repeated = await client.get(
                    f"/api/service/files/v1/{file_id}/download", follow_redirects=True
                )
                assert repeated.status_code == 200 and repeated.content == payload
                digests.append(hashlib.sha256(payload).hexdigest())
            assert len(set(digests)) == 2, "literal_artifacts_not_distinct"
        finally:
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"


async def test_delivered_pdf_hash_matches_outbox_and_owned_library_row():
    # Read-only certification of the preceding isolated account's deliveries.
    # The process reads deployment config internally, never exporting credentials.
    probe = """
import asyncio,json,logging
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
logging.disable(logging.CRITICAL)
async def main():
 try:
  async with PgConnector(Config().pg).get_session_context() as session:
   result=await session.execute(text('''
    SELECT j.user_file_id AS file_id,j.artifact_sha256 AS artifact_sha256,
           f.content_sha256 AS content_sha256
    FROM profile.document_publication_job j
    JOIN profile."user" u ON u.id=j.user_id
    JOIN profile.user_file f ON f.id=j.user_file_id AND f.user_id=j.user_id
    WHERE u.email=:email AND j.status='delivered' AND j.role='pdf'
    ORDER BY j.created_at DESC LIMIT 2
   '''),{'email':'s37-e2e-391e5206659a3654@example.com'})
   print(json.dumps([dict(r,file_id=str(r['file_id'])) for r in result.mappings()]))
 except Exception:
  print('[]'); raise SystemExit(1)
asyncio.run(main())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "publication_hash_probe_failed"
    rows = json.loads(result.stdout)
    assert len(rows) == 2, "two_delivered_pdf_rows_required"
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        timeout=60,
    ) as client:
        digests = []
        for row in rows:
            file_id = str(UUID(row["file_id"]))
            response = await client.get(
                f"/api/service/files/v1/{file_id}/download", follow_redirects=True
            )
            assert response.status_code == 200, "owned_pdf_download_failed"
            actual = hashlib.sha256(response.content).hexdigest()
            assert actual == row["artifact_sha256"] == row["content_sha256"]
            digests.append(actual)
        assert len(set(digests)) == 2
