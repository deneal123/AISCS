"""Opt-in cancellation settlement with real SQL and disposable object storage."""

import ast
import os

import pytest

from tests.test_direct_upload_live import _run_minio_probe

_MODULES = (
    "service/services/files/application/file_saver_service.py",
    "service/services/files/application/commit_resolution.py",
    "service/services/files/persistence/file_repository.py",
    "service/infrastructure/storage/minio_file_storage.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config,MinioConfig
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.application import commit_resolution
from service.services.files.persistence.file_repository import FileRepository
from service.models.key_value import ServiceType
values=json.loads(sys.stdin.read()); identity=values['identity']; stage='source_parity'
async def main():
 global stage
 modules=(sys.modules[FileSaverService.__module__],commit_resolution,
  sys.modules[FileRepository.__module__],sys.modules[MinioFileStorage.__module__])
 for module,expected in zip(modules,values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True); storage=None; owner=None; intents=[]
 repository=FileRepository(connector); payload=b'synthetic metadata cancellation fixture'
 prefix='cancel-commit/'+identity+'/'
 try:
  storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
   endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
   bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
   retry_attempts=1,retry_backoff=0,presign_expiry=60))
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'}); assert owner is not None
  class CancelCommit:
   def __init__(self,committed): self.committed=committed
   def __getattr__(self,name): return getattr(repository,name)
   async def add_file_metadata(self,row):
    async with connector.get_session_context() as db:
     await repository.add_file_metadata(row,session=db); await db.flush()
     if self.committed: await db.commit()
     raise asyncio.CancelledError('private-cancelled-commit-fixture')
  async def chunks(): yield payload
  for streaming in (False,True):
   for committed in (False,True):
    stage='stream_commit' if streaming else 'buffered_commit'
    intent=uuid.uuid4(); intents.append(intent)
    saver=FileSaverService(CancelCommit(committed),'cancel-commit/'+identity,storage)
    try:
     if streaming:
      await saver.save_stream(owner,ServiceType.CHAT,'fixture.pdf',chunks(),
       expected_size=len(payload),expected_sha256=hashlib.sha256(payload).hexdigest(),
       upload_intent_id=intent)
     else:
      await saver.save(owner,ServiceType.CHAT,'fixture.pdf',payload,upload_intent_id=intent)
     raise AssertionError('cancellation_became_success')
    except asyncio.CancelledError: pass
    row=await repository.fetch_user_file_by_upload_intent(owner,intent)
    if committed:
     assert row is not None and row.file_name.startswith(prefix)
     response=await asyncio.to_thread(storage._client.get_object,storage._bucket,row.file_name)
     try: assert response.read()==payload
     finally: response.close(); response.release_conn()
    else: assert row is None
  stage='post_upload_second_disconnect'
  entered,release,deleted=asyncio.Event(),asyncio.Event(),asyncio.Event()
  checks=0; delete_calls=0; metadata_calls=0
  class GuardedStorage:
   def __getattr__(self,name): return getattr(storage,name)
   async def delete_file(self,*,file_key):
    nonlocal delete_calls
    assert file_key.startswith(prefix)
    delete_calls+=1; entered.set(); await release.wait()
    await storage.delete_file(file_key=file_key); deleted.set()
  class NoMetadata:
   def __getattr__(self,name): return getattr(repository,name)
   async def add_file_metadata(self,row):
    nonlocal metadata_calls
    metadata_calls+=1; raise AssertionError('unexpected_metadata_attempt')
  async def guard():
   nonlocal checks
   checks+=1
   if checks==2: raise asyncio.CancelledError()
  intent=uuid.uuid4(); intents.append(intent)
  saver=FileSaverService(NoMetadata(),'cancel-commit/'+identity,GuardedStorage())
  task=asyncio.create_task(saver.save_stream(owner,ServiceType.CHAT,'fixture.pdf',chunks(),
   expected_size=len(payload),expected_sha256=hashlib.sha256(payload).hexdigest(),
   upload_intent_id=intent,before_persist=guard))
  try:
   await asyncio.wait_for(entered.wait(),5)
   task.cancel(); await asyncio.sleep(0); release.set()
   try:
    await asyncio.wait_for(task,10); raise AssertionError('cancellation_became_success')
   except asyncio.CancelledError: pass
   assert deleted.is_set() and delete_calls==1 and metadata_calls==0 and checks==2
   assert await repository.fetch_user_file_by_upload_intent(owner,intent) is None
  finally:
   release.set()
   await asyncio.gather(task,return_exceptions=True)
  stage='inventory'
  objects=list(storage._client.list_objects(storage._bucket,recursive=True))
  assert len(objects)==2 and all(item.object_name.startswith(prefix) for item in objects)
  async with connector.get_session_context() as db:
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
    'WHERE user_id=:owner AND upload_intent_id=ANY(:intents)'),
    {'owner':owner,'intents':intents})==2
 finally:
  if owner is not None and storage is not None:
   files=FileSaverService(repository,'cancel-commit/'+identity,storage)
   for intent in intents:
    row=await repository.fetch_user_file_by_upload_intent(owner,intent)
    if row is not None:
     assert row.file_name.startswith(prefix); await files.delete(owner,row.id)
   for item in storage._client.list_objects(storage._bucket,recursive=True):
    assert item.object_name.startswith(prefix); await storage.delete_file(file_key=item.object_name)
   assert not list(storage._client.list_objects(storage._bucket,recursive=True))
   if intents:
    async with connector.get_session_context() as db:
     assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
      'WHERE user_id=:owner AND upload_intent_id=ANY(:intents)'),
      {'owner':owner,'intents':intents})==0
  if storage is not None: storage._client._http.clear()
  await connector.close()
 return {'status':'passed','cancelled_calls':5,'committed_preserved':2,
  'rolled_back_compensated':2,'post_upload_compensated':True,'fixture_cleaned':True}
try: report=asyncio.run(main())
except BaseException: report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed': raise SystemExit(1)
"""


def _native_probe(ownership_failure):
    if not ownership_failure:
        return _PROBE
    marker = "if checks==2: raise asyncio.CancelledError()"
    assert _PROBE.count(marker) == 1, "post_upload_fixture_drift"
    return _PROBE.replace(
        marker, "if checks==2: raise PermissionError('private-ownership-failure-marker')", 1
    )


@pytest.mark.parametrize("ownership_failure", [False, True])
def test_metadata_cancellation_probe_compiles_without_execution(ownership_failure):
    ast.parse(_native_probe(ownership_failure))


@pytest.mark.skipif(
    os.getenv("S37_LIVE_METADATA_CANCEL") != "1", reason="dev SQL + disposable MinIO"
)
@pytest.mark.parametrize("ownership_failure", [False, True])
def test_metadata_cancel_retains_committed_and_compensates_rollback(ownership_failure):
    _run_minio_probe(
        real_persistence=True,
        probe=_native_probe(ownership_failure),
        modules=_MODULES,
        probe_timeout=90,
        expected_report={
            "status": "passed",
            "cancelled_calls": 5,
            "committed_preserved": 2,
            "rolled_back_compensated": 2,
            "post_upload_compensated": True,
            "fixture_cleaned": True,
        },
    )
