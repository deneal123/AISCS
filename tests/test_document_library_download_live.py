"""Read-only authenticated downloads of previously delivered dev document artifacts."""

import ast
import asyncio
import hashlib
import json
import logging
import os
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from PyPDF2 import PdfReader

_PROBE = r"""
import asyncio,json,logging
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.models.key_value import UserTypes
from service.services.profile.application.auth_service import AuthService
logging.disable(logging.CRITICAL)
stage='configuration'
async def main():
 global stage
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 try:
  async with connector.get_session_context() as db:
   stage='owner'
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   stage='private_http_auth'
   # The HTTP seam validates a signed JWT, not the WS session registry. Use
   # its production token factory without rotating or creating DB sessions.
   auth=AuthService(cfg.auth.model_copy(update={'jwt_exp_hours':1}),None,None,cfg.email)
   token=auth._create_jwt(owner,None,UserTypes.REGISTERED)
   stage='delivered_files'
   rows=(await db.execute(text('SELECT DISTINCT ON (j.role) f.id,j.role,j.thread_id,'
    'f.original_name,j.artifact_sha256,'
    'j.artifact_size,j.mime_type FROM profile.document_publication_job j '
    'JOIN profile.user_file f ON f.id=j.user_file_id AND f.user_id=j.user_id '
    'WHERE j.user_id=:owner AND j.status=\'delivered\' '
    'AND f.content_sha256=j.artifact_sha256 '
    'ORDER BY j.role,j.updated_at DESC LIMIT 2'),{'owner':owner})).mappings().all()
   assert {row['role'] for row in rows}=={'pdf','source_bundle'}
   print(json.dumps({'token':token,'owner':str(owner),
    'files':[{**dict(row),'id':str(row['id']),'thread_id':str(row['thread_id'])}
     for row in rows]}))
 finally: await connector.close()
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'unavailable','stage':stage})); raise SystemExit(1)
"""

# Browser acceptance needs an actual retained assistant card, not merely a
# durable Library object whose source chat was legitimately deleted. This
# query remains read-only and owner-bound; no history is seeded for acceptance.
_BROWSER_PROBE = _PROBE.replace(
    "AND f.content_sha256=j.artifact_sha256 ",
    "AND f.content_sha256=j.artifact_sha256 "
    "AND EXISTS (SELECT 1 FROM profile.chat_threads t "
    "JOIN profile.chat_messages m ON m.thread_id=t.id "
    "WHERE t.thread_id=j.thread_id AND t.user_id=j.user_id "
    "AND m.id=j.assistant_message_id "
    r"AND m.metadata->\'generated_files\' @> "
    r"jsonb_build_array(jsonb_build_object(\'file_id\',f.id::text))) ",
)

# Only ownership acceptance needs a second actor. Ordinary/browser download
# fixtures must not become dependent on another account's continued presence.
_OWNERSHIP_PROBE = _PROBE.replace(
    "   stage='delivered_files'",
    "   stage='other_dev_owner'\n"
    "   other_owner=await db.scalar(text('SELECT id FROM profile.\"user\" WHERE email=:email'),\n"
    "    {'email':'s38-video-acceptance@example.com'})\n"
    "   assert other_owner is not None and other_owner!=owner\n"
    "   other_token=auth._create_jwt(other_owner,None,UserTypes.REGISTERED)\n"
    "   stage='delivered_files'",
).replace(
    "'owner':str(owner),",
    "'owner':str(owner),'other_token':other_token,'other_owner':str(other_owner),",
)


def test_ownership_fixture_is_read_only_and_does_not_couple_browser_preparation():
    ast.parse(_OWNERSHIP_PROBE)
    assert "other_dev_owner" not in _PROBE and "other_dev_owner" not in _BROWSER_PROBE
    assert "other_owner!=owner" in _OWNERSHIP_PROBE
    assert not any(
        word in _OWNERSHIP_PROBE for word in ("INSERT", "UPDATE", "DELETE", "create_session")
    )


def test_library_download_probe_is_read_only_python():
    ast.parse(_PROBE)
    assert not any(word in _PROBE for word in ("INSERT", "UPDATE", "DELETE", "create_session"))


def test_live_download_clients_never_send_jwt_or_signed_urls_through_ambient_proxy():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    clients = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "AsyncClient"
    ]
    assert len(clients) == 4
    for node in clients:
        options = {keyword.arg: keyword.value for keyword in node.keywords}
        assert isinstance(options.get("trust_env"), ast.Constant), node.lineno
        assert options["trust_env"].value is False, node.lineno


def test_browser_library_probe_requires_retained_owned_assistant_card():
    ast.parse(_BROWSER_PROBE)
    assert _BROWSER_PROBE != _PROBE
    assert "t.user_id=j.user_id" in _BROWSER_PROBE
    assert "m.id=j.assistant_message_id" in _BROWSER_PROBE
    assert "jsonb_build_object('file_id',f.id::text)" in _BROWSER_PROBE.replace(r"\'", "'")
    assert not any(
        word in _BROWSER_PROBE for word in ("INSERT", "UPDATE", "DELETE", "create_session")
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_LIBRARY_DOWNLOAD") != "1", reason="read-only owned dev document download"
)
async def test_delivered_pdf_and_zip_are_downloadable_with_exact_library_integrity(monkeypatch):
    # httpx INFO logs include the full request URL; transport tracing may also
    # include signed query/header material. Keep that out even with log-cli enabled.
    for name in (
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
    ):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    # stdout is a private subprocess pipe, never printed, persisted or included
    # in assertions. Private short-lived dev JWT leaves existing sessions intact.
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=_OWNERSHIP_PROBE.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    fixture = json.loads(result.stdout)
    assert result.returncode == 0, f"library_download_fixture_{fixture.get('stage', 'unavailable')}"
    try:
        async with httpx.AsyncClient(
            base_url="http://localhost:8001", timeout=30, trust_env=False
        ) as anonymous:
            for item in fixture["files"]:
                response = await anonymous.get(f"/api/service/files/v1/{item['id']}/download")
                assert response.status_code in {401, 403}, "anonymous_document_download_not_denied"
                assert "location" not in response.headers
                assert response.headers.get("cache-control") == "private, no-store", (
                    "anonymous_document_cache_policy_missing"
                )
        async with httpx.AsyncClient(
            base_url="http://localhost:8001",
            cookies={"auth_token": fixture["other_token"]},
            timeout=30,
            trust_env=False,
        ) as other_owner:
            profile = await other_owner.get("/api/profile/me")
            assert profile.status_code == 200, "other_library_actor_unavailable"
            assert str(profile.json()["id"]) == fixture["other_owner"], (
                "other_library_actor_mismatch"
            )
            for item in fixture["files"]:
                response = await other_owner.get(f"/api/service/files/v1/{item['id']}/download")
                assert response.status_code == 404, "cross_owner_document_download_not_denied"
                assert "location" not in response.headers, "cross_owner_download_redirect_leaked"
                assert response.headers.get("cache-control") == "private, no-store", (
                    "cross_owner_download_cache_policy_missing"
                )
        async with httpx.AsyncClient(
            base_url="http://localhost:8001",
            cookies={"auth_token": fixture["token"]},
            timeout=30,
            trust_env=False,
        ) as owner:
            profile = await owner.get("/api/profile/me")
            assert profile.status_code == 200, "library_download_session_unavailable"
            assert str(profile.json()["id"]) == fixture["owner"], "library_download_actor_mismatch"
            for item in fixture["files"]:
                response = await owner.get(f"/api/service/files/v1/{item['id']}/download")
                assert response.status_code == 307, "library_download_redirect_unavailable"
                assert response.headers.get("cache-control") == "private, no-store", (
                    "library_download_redirect_cache_policy_missing"
                )
                assert {"cookie", "authorization"} <= {
                    value.strip().lower() for value in response.headers.get("vary", "").split(",")
                }, "library_download_redirect_auth_vary_missing"
                # Do not carry backend cookies to the external storage origin.
                async with httpx.AsyncClient(timeout=30, trust_env=False) as storage:
                    async with storage.stream("GET", response.headers["location"]) as stream:
                        assert stream.status_code == 200, "library_download_object_unavailable"
                        assert stream.headers.get("cache-control") == "private, no-store", (
                            "library_download_storage_cache_policy_missing"
                        )
                        content_type = stream.headers.get("content-type", "").split(";", 1)[0]
                        assert content_type in {item["mime_type"], "application/octet-stream"}, (
                            "library_download_mime_mismatch"
                        )
                        digest = hashlib.sha256()
                        content = BytesIO()
                        async for chunk in stream.aiter_bytes():
                            assert content.tell() + len(chunk) <= item["artifact_size"], (
                                "library_download_size_exceeded"
                            )
                            digest.update(chunk)
                            content.write(chunk)
                assert content.tell() == item["artifact_size"], "library_download_size_mismatch"
                assert digest.hexdigest() == item["artifact_sha256"], (
                    "library_download_hash_mismatch"
                )
                content.seek(0)
                if item["role"] == "pdf":
                    assert len(PdfReader(content).pages) > 0, "library_download_pdf_invalid"
                else:
                    with ZipFile(content) as bundle:
                        assert bundle.testzip() is None, "library_download_source_bundle_invalid"
                        assert any(name.endswith("main.tex") for name in bundle.namelist()), (
                            "library_download_source_entrypoint_missing"
                        )
    except (httpx.HTTPError, OSError, ValueError):
        pytest.fail("library_download_transport_or_format_failed", pytrace=False)
