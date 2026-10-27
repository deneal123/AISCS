"""Opt-in owned dev HTTP upload/list/download; no chat message or model calls."""

import ast
import base64
import hashlib
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from tests.test_document_storage_process_recovery_live import _docker, _report
from tests.test_file_download_http_live import _ensure_dev_ready, _request

_MODULES = (
    "service/services/files/application/library_file_type.py",
    "service/services/files/application/file_saver_service.py",
    "service/services/chat/application/use_cases/upload_file_use_case.py",
    "service/services/chat/presentation/http/upload_api.py",
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/domain/download_filename.py",
    "service/services/files/presentation/routers/files_api/files_api.py",
)
_PROBE = r"""
import asyncio,base64,hashlib,json,logging,sys,uuid
from pathlib import Path
from urllib.parse import urlsplit
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from minio.error import S3Error
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application import library_file_type as kinds
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository
from service.services.profile.application.auth_service import AuthService
from service.services.billing.application.billing_service import BillingService
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.application.use_cases import upload_file_use_case as intake
from service.services.chat.presentation.http import upload_api as upload
from service.services.files.domain import download_filename as names
from service.services.files.presentation.routers.files_api import files_api as routes
from service.models.key_value import UserTypes,ServiceType
values=json.loads(sys.stdin.read()); stage='source_parity'
async def main():
 global stage
 for module,expected in zip((kinds,sys.modules[FileSaverService.__module__],intake,upload,
  sys.modules[MinioFileStorage.__module__],names,routes),
  values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected
 cfg=Config(); assert cfg.pg.host=='postgres' and cfg.storage.backend=='minio'
 connector=PgConnector(cfg.pg,force_new=True); storage=None
 try:
  stage='fixture_owner'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
  identity=uuid.UUID(values['identity']); repository=FileRepository(connector)
  async def accounting():
   balance=await BillingService(BillingRepository(connector),cfg.billing).get_balance(str(owner))
   async with connector.get_session_context() as db:
    count=await db.scalar(text("SELECT count(*) FROM profile.billing_events "
     "WHERE user_id=:owner AND event_type='usage'"),{'owner':owner})
   return {'balance':balance.total,'usage_event_count':count}
  if values['mode']=='prepare':
   assert await repository.fetch_user_file_by_upload_intent(owner,identity) is None
   seeded=None
   if values.get('seed_body'):
    storage=await asyncio.to_thread(MinioFileStorage,cfg.minio)
    saved=await FileSaverService(repository,'uploads',storage).save(
     owner,ServiceType.CHAT,values['name'],base64.b64decode(values['seed_body']),upload_intent_id=identity)
    seeded=str(saved.file_id)
   auth=AuthService(cfg.auth,None,None,cfg.email)
   endpoint=cfg.minio.public_endpoint or cfg.minio.endpoint
   host=urlsplit(endpoint if '://' in endpoint else 'http://'+endpoint).hostname
   assert host
   return {'status':'prepared','token':auth._create_jwt(owner,None,UserTypes.REGISTERED),
    'download_host':host,'seeded_file_id':seeded,'accounting':await accounting()}
  stage='owned_persistence'
  row=await repository.fetch_user_file_by_upload_intent(owner,identity)
  if values['mode']=='verify_absent':
   assert row is None
   return {'status':'verified_absent','owned_intent_absent':True,'accounting':await accounting()}
  if row is not None:
   assert row.original_name==values['name'] and row.user_id==owner
   storage=await asyncio.to_thread(MinioFileStorage,cfg.minio)
   if values['mode']=='verify':
    assert str(row.id)==values['file_id']
    assert row.content_sha256==values['sha256']
    assert hashlib.sha256(await storage.get_file(row.file_name)).hexdigest()==values['sha256']
    return {'status':'verified','one_owned_intent':True,'stored_digest_matches':True}
   assert values['mode']=='cleanup'
   stage='fixture_cleanup'
   await storage.delete_file(file_key=row.file_name)
   try: await asyncio.to_thread(storage._client.stat_object,storage._bucket,row.file_name)
   except S3Error as error: assert error.code=='NoSuchKey'
   else: raise AssertionError()
   await repository.delete_file_metadata(user_id=owner,file_id=row.id)
  else:
   assert values['mode']=='cleanup'
  assert await repository.fetch_user_file_by_upload_intent(owner,identity) is None
  return {'status':'cleaned','fixture_cleaned':True,'accounting':await accounting()}
 finally:
  if storage is not None: storage._client._http.clear()
  await connector._engine.dispose()
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def _probe(values, mode):
    try:
        result = _docker(
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            _PROBE,
            input=json.dumps({**values, "mode": mode}).encode(),
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        # A subprocess exception can echo code or captured private output.
        # Match the existing dev SQL/S3 HTTP-probe budget, never expose either.
        raise RuntimeError("library_fixture_timeout") from None
    report = _report(result)
    if result.returncode:
        raise RuntimeError(f"library_fixture_failed:{report.get('stage', 'unknown')}")
    return report


def test_library_probe_is_valid_python():
    ast.parse(_PROBE)


def test_probe_timeout_does_not_expose_captured_credentials(monkeypatch):
    marker = "PRIVATE_CAPTURED_AUTH_TOKEN"

    def expire(*_args, **_kwargs):
        raise subprocess.TimeoutExpired([marker], 60, output=marker.encode())

    monkeypatch.setattr("tests.test_library_file_types_live._docker", expire)
    with pytest.raises(RuntimeError, match="^library_fixture_timeout$") as caught:
        _probe({}, "verify")
    assert marker not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_LIBRARY_TYPES") != "1", reason="owned dev HTTP fixture")
async def test_deployed_missing_filename_has_no_file_or_charge(monkeypatch):
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    identity = uuid.uuid4().hex
    values = {
        "identity": identity,
        "name": f"s37-empty-{identity[:12]}.txt",
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
    }
    private = None
    await _ensure_dev_ready()
    try:
        private = _probe(values, "prepare")
        # HTTPX omits the filename parameter for an empty name, which turns
        # this into a text field (422). Preserve an explicit empty filename
        # to exercise the declared UploadFile precheck, not a different case.
        multipart = (
            f'--{identity}\r\nContent-Disposition: form-data; name="file"; filename=""\r\n'
            "Content-Type: text/plain\r\n\r\nsynthetic\r\n"
            f'--{identity}\r\nContent-Disposition: form-data; name="upload_intent_id"\r\n\r\n'
            f"{identity}\r\n--{identity}--\r\n"
        ).encode()
        async with httpx.AsyncClient(
            base_url="http://localhost:8001", timeout=20, trust_env=False
        ) as client:
            response = await _request(
                client,
                "/api/chats/upload",
                method="POST",
                headers={
                    "Cookie": "auth_token=" + private["token"],
                    "Content-Type": f"multipart/form-data; boundary={identity}",
                },
                content=multipart,
            )
        assert response.status_code == 400
        assert response.json()["error"]["message"] == "No file provided"
        assert set(response.json()) == {"error"}
        verified = _probe(values, "verify_absent")
        assert verified["owned_intent_absent"]
        assert verified["accounting"] == private["accounting"]
    finally:
        cleaned = _probe(values, "cleanup")
        assert cleaned["fixture_cleaned"]
        if private is not None:
            assert cleaned["accounting"] == private["accounting"]


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_LIBRARY_TYPES") != "1", reason="owned dev HTTP fixture")
@pytest.mark.parametrize("seeded", [False, True], ids=["new-whitespace", "owned-text-replay"])
async def test_deployed_chat_upload_replay_library_kind_and_download(monkeypatch, seeded):
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    identity = uuid.uuid4().hex
    # Display metadata needs no semantic text. Empty-after-strip content skips
    # production graph indexing without changing shared runtime settings.
    body = b"Synthetic existing Library source.\n" if seeded else b" \n\t\n"
    values = {
        "identity": identity,
        "name": f"s37-library-{identity}.txt" if seeded else f"Материалы (1)-{identity}.txt",
        "sha256": hashlib.sha256(body).hexdigest(),
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
    }
    if seeded:
        # Seed using the persistence seam, not a paid upload/indexing call.
        # Both HTTP requests must reuse that already-owned source.
        values["seed_body"] = base64.b64encode(body).decode()
    await _ensure_dev_ready()
    private = None
    try:
        private = _probe(values, "prepare")
        async with httpx.AsyncClient(
            base_url="http://localhost:8001",
            timeout=30,
            trust_env=False,
        ) as client:
            headers = {"Cookie": "auth_token=" + private["token"]}
            file_id = None
            for _ in range(2):
                uploaded = await _request(
                    client,
                    "/api/chats/upload",
                    method="POST",
                    headers=headers,
                    files={"file": (values["name"], body, "text/plain")},
                    data={"upload_intent_id": identity},
                )
                assert uploaded.status_code == 200, "chat_upload_failed"
                returned = str(uuid.UUID(uploaded.json()["file_id"]))
                if seeded:
                    assert returned == private["seeded_file_id"], "seeded_source_not_reused"
                if file_id is not None:
                    assert returned == file_id, "upload_replay_created_duplicate"
                file_id = returned
            values["file_id"] = file_id
            listed = await _request(client, "/api/chats/work-library?limit=200", headers=headers)
            assert listed.status_code == 200, "library_list_failed"
            matches = [item for item in listed.json()["items"] if item["file_id"] == file_id]
            assert matches == [
                {
                    "file_id": file_id,
                    "name": values["name"],
                    "file_type": "text",
                    "availability": "ready",
                }
            ], "unsafe_or_wrong_library_projection"
            route = f"/api/service/files/v1/{file_id}/download"
            signed = await _request(client, route, headers=headers)
            assert signed.status_code == 307, "owned_download_failed"
            location = signed.headers.get("location", "")
            endpoint = httpx.URL(location)
            if endpoint.scheme not in {"http", "https"}:
                raise RuntimeError("invalid_download_scheme")
            if endpoint.host != private["download_host"]:
                raise RuntimeError("unconfigured_storage_redirect")
            downloaded = await _request(client, location)
            assert downloaded.status_code == 200, "storage_download_failed"
            disposition = downloaded.headers.get("content-disposition", "")
            assert disposition.startswith('attachment; filename="'), "download_name_missing"
            assert disposition.isascii(), "invalid_header_encoding"
            encoded_name = disposition.split("filename*=UTF-8''", 1)[-1]
            assert unquote(encoded_name) == values["name"], "download_filename_mismatch"
            assert downloaded.headers.get("content-type", "").split(";")[0] in {
                "text/plain",
                "application/octet-stream",
            }, "unexpected_download_mime"
            assert hashlib.sha256(downloaded.content).hexdigest() == values["sha256"], (
                "download_digest_mismatch"
            )
            assert _probe(values, "verify")["stored_digest_matches"]
    finally:
        cleaned = _probe(values, "cleanup")
        assert cleaned["fixture_cleaned"], "owned_fixture_cleanup_failed"
        if private is not None:
            assert cleaned["accounting"] == private["accounting"], "unexpected_paid_background_pass"
