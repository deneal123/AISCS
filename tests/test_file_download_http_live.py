"""Opt-in deployed dev HTTP auth/download; exact SQL/S3 fixture cleanup."""

import ast
import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path

import httpx
import pytest

from tests.test_document_storage_process_recovery_live import _docker, _report

_MODULES = (
    "service/services/files/application/file_saver_service.py",
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/persistence/file_repository.py",
    "service/services/profile/application/auth_service.py",
)

_PROBE = r"""
import asyncio,base64,hashlib,json,logging,sys,uuid
from pathlib import Path
from urllib.parse import urlsplit
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository
from service.services.profile.application.auth_service import AuthService
from service.models.key_value import ServiceType,UserTypes
from service.infrastructure.cache.manager import RedisManager
from service.infrastructure.cache.cache import RedisCacheService
values=json.loads(sys.stdin.read()); stage='source_parity'
async def main():
 global stage
 for cls,expected in zip((FileSaverService,MinioFileStorage,FileRepository,AuthService),
  values['digests'],strict=True):
   source=Path(sys.modules[cls.__module__].__file__).read_bytes()
   assert hashlib.sha256(source).hexdigest()==expected
 cfg=Config(); assert cfg.pg.host=='postgres' and cfg.storage.backend=='minio'
 identity=uuid.UUID(values['identity']); prefix='s37-http/'+identity.hex+'/'
 connector=PgConnector(cfg.pg,force_new=True); storage=None; owner=None
 repository=FileRepository(connector); prepared=False
 async def drain_scan(file_key,client):
  stream='file:'+file_key+':stream'
  removed=await client.lrem('file:scan:queue',0,file_key)
  if not removed:
   for attempt in range(60):
    if await client.exists(stream): break
    await asyncio.sleep(0.2)
   else: raise RuntimeError('fixture_scan_cleanup_unconfirmed')
  await client.delete(stream)
 async def cleanup():
  if values.get('direct_offers'):
   manager_local=RedisManager(cfg.redis)
   client=manager_local.get_client(); cache=RedisCacheService(client,cfg.redis)
   try:
    for offer in values['direct_offers']:
     file_id=uuid.UUID(offer['file_id'])
     source='uploads/CHAT/pending/'+owner.hex+'/'+file_id.hex+'.png'
     assert offer['file_key']==source
     direct=await repository.fetch_user_file_by_id(owner,file_id)
     if direct is not None:
      assert direct.upload_intent_id==file_id
      assert direct.original_name=='s37-http-'+identity.hex+'.png'
      assert direct.file_name.startswith('uploads/CHAT/') and '/pending/' not in direct.file_name
      if not offer.get('scan_drained'):
       await drain_scan(direct.file_name,client)
      await storage.delete_file(file_key=direct.file_name)
      await repository.delete_file_metadata(user_id=owner,file_id=file_id)
     await storage.delete_file(file_key=source)
     for namespace in ('file_upload_admission','file_upload_scan'):
      await cache.invalidate(namespace,str(file_id))
      assert await cache.get_json(namespace,str(file_id)) is None
     assert await repository.fetch_user_file_by_id(owner,file_id) is None
   finally: await manager_local.close()
  row=await repository.fetch_user_file_by_upload_intent(owner,identity)
  if row is not None:
   assert row.file_name.startswith(prefix) and row.user_id==owner
   await storage.delete_file(file_key=row.file_name)
   await repository.delete_file_metadata(user_id=owner,file_id=row.id)
  assert await repository.fetch_user_file_by_upload_intent(owner,identity) is None
  for item in storage._client.list_objects(storage._bucket,prefix=prefix,recursive=True):
   assert item.object_name.startswith(prefix)
   await storage.delete_file(file_key=item.object_name)
  assert not list(storage._client.list_objects(storage._bucket,prefix=prefix,recursive=True))
 try:
  stage='fixture_owner'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   other=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None and other is not None and owner!=other
  storage=await asyncio.to_thread(MinioFileStorage,cfg.minio)
  if values['mode']=='drain_direct':
   stage='direct_scanner_drain'
   assert len(values['direct_offers'])==1
   direct_id=uuid.UUID(values['direct_offers'][0]['file_id'])
   row=await repository.fetch_user_file_by_id(owner,direct_id)
   assert row is not None and row.upload_intent_id==direct_id
   assert row.original_name=='s37-http-'+identity.hex+'.png'
   manager=RedisManager(cfg.redis)
   try: await drain_scan(row.file_name,manager.get_client())
   finally: await manager.close()
   prepared=True
   return {'status':'drained','fixture_scan_drained':True}
  if values['mode']=='inspect_direct':
   stage='direct_sql_verification'
   assert len(values['direct_offers'])==1
   direct_id=uuid.UUID(values['direct_offers'][0]['file_id'])
   row=await repository.fetch_user_file_by_id(owner,direct_id)
   assert row is not None and row.upload_intent_id==direct_id
   assert row.original_name=='s37-http-'+identity.hex+'.png'
   assert row.file_name!=values['direct_offers'][0]['file_key']
   assert hashlib.sha256(await storage.get_file(row.file_name)).hexdigest()==values['sha256']
   prepared=True
   return {'status':'checked','one_issued_row':True,'private_copy_intact':True}
  if values['mode']=='cleanup':
   stage='fixture_cleanup'; await cleanup()
   return {'status':'cleaned','fixture_cleaned':True}
  assert values['mode']=='prepare'
  stage='fixture_save'
  body=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=')
  saver=FileSaverService(repository,prefix.rstrip('/'),storage)
  saved=await saver.save(owner,ServiceType.CHAT,'fixture.png',body,upload_intent_id=identity)
  assert saved.file_key.startswith(prefix)
  auth=AuthService(cfg.auth,None,None,cfg.email)
  # Existing auth issuer/validator contract; this does not certify login/OTP.
  owner_token=auth._create_jwt(owner,None,UserTypes.REGISTERED)
  other_token=auth._create_jwt(other,None,UserTypes.REGISTERED)
  capability=await saver.get_presigned_url_by_key(file_key=saved.file_key)
  assert capability is not None
  download_host=urlsplit(capability).hostname
  assert download_host
  prepared=True
  return {'status':'prepared','file_id':str(saved.file_id),'owner_token':owner_token,
   'other_token':other_token,'sha256':hashlib.sha256(body).hexdigest(),'size':len(body),
   'download_host':download_host,'owner_id':str(owner)}
 finally:
  try:
   if not prepared and storage is not None and owner is not None: await cleanup()
  finally:
   if storage is not None: storage._client._http.clear()
   await connector._engine.dispose()
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_download_http_probe_is_valid_python():
    ast.parse(_PROBE)


def _probe(values, mode):
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
    report = _report(result)
    if result.returncode:
        raise RuntimeError(f"download fixture failed at {report.get('stage', 'unknown')}")
    return report


async def _request(client, path, *, method="GET", **kwargs):
    try:
        return await client.request(method, path, **kwargs)
    except httpx.HTTPError:
        raise RuntimeError("download_http_unavailable") from None


async def _ensure_dev_ready():
    async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
        for _ in range(30):
            try:
                response = await client.get("http://localhost:8001/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("dev_backend_health_unavailable")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_FILE_DOWNLOAD_HTTP") != "1", reason="owned dev HTTP fixture"
)
async def test_deployed_http_owned_download_foreign_and_anonymous_rejected(monkeypatch):
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    values = {
        "identity": uuid.uuid4().hex,
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
    }
    prepared = False
    try:
        await _ensure_dev_ready()
        report = _probe(values, "prepare")
        prepared = True
        assert report["status"] == "prepared", "fixture_not_prepared"
        file_id = str(uuid.UUID(report["file_id"]))
        route = f"/api/service/files/v1/{file_id}/download"
        async with httpx.AsyncClient(
            base_url="http://localhost:8001",
            timeout=20,
            trust_env=False,
        ) as client:
            owner_headers = {"Cookie": "auth_token=" + report["owner_token"]}
            signed = await _request(client, route, headers=owner_headers)
            assert signed.status_code == 307, "owner_download_redirect_failed"
            location = signed.headers.get("location", "")
            endpoint = httpx.URL(location)
            if endpoint.scheme not in {"http", "https"}:
                raise RuntimeError("invalid_download_scheme")
            if endpoint.host != report["download_host"]:
                raise RuntimeError("unconfigured_storage_redirect")
            downloaded = await _request(client, location)
            assert downloaded.status_code == 200, "storage_http_download_failed"
            assert len(downloaded.content) == report["size"], "download_size_mismatch"
            assert hashlib.sha256(downloaded.content).hexdigest() == report["sha256"], (
                "download_digest_mismatch"
            )
            assert downloaded.headers.get("content-type", "").split(";")[0] in {
                "image/png",
                "application/octet-stream",
            }, "download_mime_mismatch"
            foreign = await _request(
                client, route, headers={"Cookie": "auth_token=" + report["other_token"]}
            )
            assert foreign.status_code == 404, "foreign_download_not_rejected"
            assert "location" not in foreign.headers, "foreign_capability_exposed"
            # No cookie jar retention from explicit request headers.
            anonymous = await _request(client, route)
            assert anonymous.status_code == 401, "anonymous_download_not_rejected"
            assert "location" not in anonymous.headers, "anonymous_capability_exposed"
            metadata = await _request(
                client, f"/api/service/files/v1/{file_id}", headers=owner_headers
            )
            assert metadata.status_code == 200, "owned_metadata_failed"
            assert metadata.json()["file_id"] == file_id, "owned_metadata_id_mismatch"
    finally:
        if prepared:
            cleanup = _probe(values, "cleanup")
            assert cleanup == {"status": "cleaned", "fixture_cleaned": True}, "cleanup_unconfirmed"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_FILE_DELETE_HTTP") != "1", reason="owned dev HTTP delete fixture"
)
async def test_deployed_http_delete_requires_owner_and_removes_object(monkeypatch):
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    values = {
        "identity": uuid.uuid4().hex,
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
    }
    prepared = False
    try:
        await _ensure_dev_ready()
        report = _probe(values, "prepare")
        prepared = True
        file_id = str(uuid.UUID(report["file_id"]))
        async with httpx.AsyncClient(
            base_url="http://localhost:8001", timeout=20, trust_env=False
        ) as client:
            owner = {"Cookie": "auth_token=" + report["owner_token"]}
            route = f"/api/service/files/v1/delete/{file_id}"
            foreign = await _request(
                client,
                route,
                method="DELETE",
                headers={"Cookie": "auth_token=" + report["other_token"]},
            )
            assert foreign.status_code == 404, "foreign_delete_not_rejected"
            anonymous = await _request(client, route, method="DELETE")
            assert anonymous.status_code == 401, "anonymous_delete_not_rejected"
            download_route = f"/api/service/files/v1/{file_id}/download"
            before = await _request(client, download_route, headers=owner)
            assert before.status_code == 307, "fixture_download_unavailable"
            location = before.headers.get("location", "")
            if httpx.URL(location).host != report["download_host"]:
                raise RuntimeError("unconfigured_download_redirect")
            deleted = await _request(client, route, method="DELETE", headers=owner)
            assert deleted.status_code == 200, "owned_delete_failed"
            after = await _request(client, download_route, headers=owner)
            assert after.status_code == 404, "deleted_file_metadata_remains"
            assert "location" not in after.headers, "deleted_file_capability_exposed"
            missing_object = await _request(client, location)
            assert missing_object.status_code == 404, "deleted_object_still_available"
    finally:
        if prepared:
            cleanup = _probe(values, "cleanup")
            assert cleanup == {"status": "cleaned", "fixture_cleaned": True}, "cleanup_unconfirmed"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_DIRECT_UPLOAD_HTTP") != "1", reason="owned dev direct PUT/callback fixture"
)
async def test_deployed_http_direct_put_callback_replay_and_private_copy(monkeypatch):
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    values = {
        "identity": uuid.uuid4().hex,
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
        "direct_offers": [],
    }
    prepared = False
    try:
        await _ensure_dev_ready()
        report = _probe(values, "prepare")
        prepared = True
        values["sha256"] = report["sha256"]
        body = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII="
        )
        async with httpx.AsyncClient(
            base_url="http://localhost:8001", timeout=20, trust_env=False
        ) as client:
            owner = {"Cookie": "auth_token=" + report["owner_token"]}
            signed = await _request(
                client,
                "/api/service/files/v1/presign/CHAT",
                method="POST",
                headers=owner,
                json={"filename": "s37-http-" + values["identity"] + ".png", "expiry_sec": 60},
            )
            if signed.status_code != 200:
                raise RuntimeError("direct_http_presign_unavailable")
            offer = signed.json()
            file_id = str(uuid.UUID(offer["file_id"]))
            pending = (
                "uploads/CHAT/pending/"
                + uuid.UUID(report["owner_id"]).hex
                + "/"
                + uuid.UUID(file_id).hex
                + ".png"
            )
            if offer["file_key"] != pending:
                raise RuntimeError("stale_direct_upload_runtime")
            values["direct_offers"].append({"file_id": file_id, "file_key": offer["file_key"]})
            endpoint = httpx.URL(offer["upload_url"])
            if endpoint.scheme not in {"http", "https"} or endpoint.host != report["download_host"]:
                raise RuntimeError("unconfigured_upload_redirect")
            uploaded = await _request(client, offer["upload_url"], method="PUT", content=body)
            assert uploaded.status_code == 200, "direct_http_put_failed"
            callback = f"/api/service/files/v1/{file_id}/callback"
            payload = {"file_key": offer["file_key"], "mode": "CHAT"}
            foreign = await _request(
                client,
                callback,
                method="POST",
                json=payload,
                headers={"Cookie": "auth_token=" + report["other_token"]},
            )
            assert foreign.status_code == 404, "foreign_callback_not_rejected"
            for _ in range(2):
                saved = await _request(client, callback, method="POST", headers=owner, json=payload)
                if saved.status_code != 200 or saved.json().get("file_id") != file_id:
                    raise RuntimeError("direct_callback_issued_id_mismatch")
            changed = await _request(client, offer["upload_url"], method="PUT", content=b"changed")
            assert changed.status_code == 200, "late_put_failed"
            checked = _probe(values, "inspect_direct")
            assert checked == {
                "status": "checked",
                "one_issued_row": True,
                "private_copy_intact": True,
            }, "direct_persistence_unconfirmed"
            download = await _request(
                client, f"/api/service/files/v1/{file_id}/download", headers=owner
            )
            assert download.status_code == 307, "direct_download_redirect_failed"
            location = download.headers.get("location", "")
            if httpx.URL(location).host != report["download_host"]:
                raise RuntimeError("unconfigured_download_redirect")
            delivered = await _request(client, location)
            assert delivered.status_code == 200, "direct_download_failed"
            assert hashlib.sha256(delivered.content).hexdigest() == report["sha256"], (
                "private_download_digest_mismatch"
            )
            drained = _probe(values, "drain_direct")
            assert drained == {"status": "drained", "fixture_scan_drained": True}, (
                "scan_drain_failed"
            )
            values["direct_offers"][0]["scan_drained"] = True
            deleted = await _request(
                client, f"/api/service/files/v1/delete/{file_id}", method="DELETE", headers=owner
            )
            assert deleted.status_code == 200, "direct_delete_failed"
            # A still-live PUT may update pending bytes, but must not republish Library.
            after_delete_put = await _request(
                client, offer["upload_url"], method="PUT", content=b"changed"
            )
            assert after_delete_put.status_code == 200, "post_delete_put_failed"
            denied = await _request(client, callback, method="POST", headers=owner, json=payload)
            assert denied.status_code == 404, "deleted_upload_resurrected"
            absent = await _request(
                client, f"/api/service/files/v1/{file_id}/download", headers=owner
            )
            assert absent.status_code == 404, "deleted_library_row_reappeared"
            assert "location" not in absent.headers, "deleted_download_capability_exposed"
            old_capability = await _request(client, location)
            assert old_capability.status_code == 404, "deleted_private_copy_survived"
    finally:
        if prepared:
            cleanup = _probe(values, "cleanup")
            assert cleanup == {"status": "cleaned", "fixture_cleaned": True}, "cleanup_unconfirmed"
