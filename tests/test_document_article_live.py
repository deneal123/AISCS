"""Opt-in metered attachment -> source-backed article -> audited Library PDF."""

import asyncio
import io
import json
import os
import re
import subprocess
import zipfile
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

from service.services.chat.infrastructure.chat_worker.context.metadata import (
    _DOCUMENT_FAILURE_CODES,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_ARTICLE") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit metered article acceptance",
    ),
]

MATERIAL = """# Материалы для краткой технической статьи
JSON служит текстовым форматом обмена структурированными данными.
Стандарт различает строки, числа, логические значения, null, объекты и массивы.
Пары имён и значений образуют объект; порядок элементов массива значим.
Эти материалы не содержат экспериментов или количественных результатов.
Не добавляйте неподтверждённые преимущества производительности.

## Источник
T. Bray, 2017. [The JavaScript Object Notation (JSON) Data Interchange Format]
(https://www.rfc-editor.org/rfc/rfc8259.html)
""".replace("]\n(", "](").encode("utf-8")


def _inspect_article(payload):
    probe = """
import json,pathlib,re,subprocess,sys
p=pathlib.Path('/tmp/article.pdf'); p.write_bytes(sys.stdin.buffer.read())
valid=subprocess.run(['qpdf','--check',str(p)],capture_output=True).returncode==0
info=subprocess.run(['pdfinfo',str(p)],capture_output=True).returncode==0
result=subprocess.run(['pdftotext','-layout',str(p),'-'],capture_output=True)
text=result.stdout.decode('utf-8'); compact=re.sub(r'[^a-z0-9]','',text.lower())
print(json.dumps({'valid':valid,'info':info,'text':result.returncode==0,
 'subject':'json' in compact,'source':'datainterchangeformat' in compact,
 'bounded':len(text.split())<=350}))
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
            "--tmpfs",
            "/tmp:rw,size=32m",
            "--entrypoint",
            "python3",
            "gpthub-document-runtime:latest",
            "-c",
            probe,
        ],
        input=payload,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "pdf_inspection_unavailable"
    assert all(json.loads(result.stdout).values()), "article_pdf_quality_failed"


async def test_owned_material_with_registered_reference_produces_downloadable_article():
    token = os.environ["E2E_AUTH_TOKEN"]
    model = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-2")
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=60
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 source article acceptance"})
        assert created.status_code == 201, "thread_create_failed"
        thread_id = str(UUID(created.json()["thread_id"]))
        try:
            uploaded = await client.post(
                "/api/chats/upload",
                data={"thread_id": thread_id, "upload_intent_id": str(uuid4())},
                files={"file": ("s37-json-materials.md", MATERIAL, "text/markdown")},
            )
            assert uploaded.status_code == 200, "attachment_upload_failed"
            file_id = str(UUID(uploaded.json()["file_id"]))
            async with (
                connect(
                    f"ws://localhost:8001/api/chats/{thread_id}/ws",
                    additional_headers={"Cookie": f"auth_token={token}"},
                    max_size=2_000_000,
                ) as socket,
                asyncio.timeout(300),
            ):
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "id": str(uuid4()),
                            "text": "Создай краткую статью в PDF по материалам, не более 200 слов. "
                            "Используй только предоставленный источник; без таблиц и исследований.",
                            "model": model,
                            "route_override": "pdf_gen",
                            "file_ids": [file_id],
                            "attachments": [{"file_id": file_id, "name": "s37-json-materials.md"}],
                            "memory_enabled": False,
                        },
                        ensure_ascii=False,
                    )
                )
                accepted = False
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") in {"claimed", "replay"}:
                        event = event.get("data") or {}
                    metadata = event.get("metadata") or {}
                    offer = metadata.get("mode_offer") or {}
                    if offer.get("offer_id") and offer.get("status") == "pending":
                        assert not accepted, "unexpected_second_offer"
                        assert int(offer.get("estimated_credits") or 0) <= 5000, (
                            "dev_budget_exceeded"
                        )
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "message",
                                    "id": str(uuid4()),
                                    "text": "",
                                    "confirm_offer_id": offer["offer_id"],
                                }
                            )
                        )
                        accepted = True
                        continue
                    if event.get("type") == "agent_reply" and metadata.get("document_outcome"):
                        break
                outcome = metadata.get("document_outcome")
                failure = metadata.get("document_failure_code")
                print(
                    "article outcome: "
                    + (
                        outcome
                        if outcome in {"failed", "deferred", "completed", "draft_ready"}
                        else "unknown"
                    )
                )
                if failure in _DOCUMENT_FAILURE_CODES:
                    print("article failure: " + failure)
                assert metadata.get("requested_authoring_model") == model
                assert metadata.get("actual_authoring_model") == model
                assert outcome in {"completed", "deferred"}, "article_not_publishable"
            async with asyncio.timeout(180):
                while True:
                    history = await client.get(f"/api/chats/{thread_id}")
                    assert history.status_code == 200, "history_unavailable"
                    messages = history.json()["messages"]
                    generated = [
                        item
                        for message in messages
                        for item in (message.get("metadata") or {}).get("generated_files") or []
                    ]
                    pdf = next(
                        (f for f in generated if f.get("mime_type") == "application/pdf"), None
                    )
                    if pdf:
                        break
                    await asyncio.sleep(2)
            downloaded = await client.get(
                f"/api/service/files/v1/{UUID(pdf['file_id'])}/download", follow_redirects=True
            )
            assert downloaded.status_code == 200, "library_download_failed"
            assert downloaded.content.startswith(b"%PDF-")
            await asyncio.to_thread(_inspect_article, downloaded.content)
        finally:
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"


async def test_persisted_article_source_bundle_contains_only_registered_reference():
    """Read-only companion, no second authoring/audit call."""
    probe = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
async def main():
 async with PgConnector(Config().pg).get_session_context() as session:
  row=await session.execute(text('''SELECT j.user_file_id FROM profile.document_publication_job j
   JOIN profile."user" u ON u.id=j.user_id
   JOIN profile.user_file f ON f.id=j.user_file_id AND f.user_id=j.user_id
   WHERE u.email=:email AND j.status='delivered' AND j.role='source_bundle'
   ORDER BY j.created_at DESC LIMIT 1'''),
   {'email':'s37-e2e-391e5206659a3654@example.com'})
  value=row.scalar_one_or_none()
  print(json.dumps({'file_id':str(value) if value else None}))
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
    assert result.returncode == 0, "bundle_lookup_unavailable"
    file_id = UUID(json.loads(result.stdout)["file_id"])
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        timeout=60,
    ) as client:
        response = await client.get(
            f"/api/service/files/v1/{file_id}/download", follow_redirects=True
        )
        assert response.status_code == 200, "bundle_download_failed"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = archive.read("document.toml").decode()
            assert 'profile_id = "generic_article"' in manifest, "article_bundle_required"
            bibliography = archive.read("bibliography/references.bib").decode()
            keys = re.findall(r"@\w+\s*\{([^,]+),", bibliography)
            assert len(keys) == 1, "unexpected_bibliography_record"
            assert "https://www.rfc-editor.org/rfc/rfc8259.html" in bibliography
            assert "The JavaScript Object Notation" in bibliography
            citations = set()
            for name in archive.namelist():
                if name.startswith("content/") and name.endswith(".tex"):
                    for value in re.findall(r"\\cite\w*\{([^}]+)\}", archive.read(name).decode()):
                        citations.update(value.split(","))
            assert citations and citations <= set(keys), "unregistered_citation"
