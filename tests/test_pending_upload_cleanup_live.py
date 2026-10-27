"""Opt-in retention on disposable S3 plus exact dev SQL/Redis fixtures, never shared S3."""

import ast
import os

import pytest

from tests.test_direct_upload_live import _run_minio_probe

_MODULES = (
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/persistence/file_repository.py",
    "service/services/files/application/pending_upload_cleanup.py",
    "service/services/files/domain/pending_upload.py",
    "service/infrastructure/cache/cache.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.persistence.file_repository import FileRepository
from service.services.files.application import pending_upload_cleanup as cleanup
from service.services.files.domain import pending_upload as inventory
from service.infrastructure.cache.cache import RedisCacheService
from service.infrastructure.cache.manager import RedisManager
from service.infrastructure.database.postgresql import PgConnector
from service.models.db.db_models import UserFile
from service.models.key_value import ServiceType
from service.settings import Config,MinioConfig
values=json.loads(sys.stdin.read()); stage='source_parity'
async def main():
 global stage
 modules=(sys.modules[MinioFileStorage.__module__],sys.modules[FileRepository.__module__],
  cleanup,inventory,sys.modules[RedisCacheService.__module__])
 for module,digest in zip(modules,values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 identity=uuid.UUID(values['identity']); cfg=Config()
 assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True); repository=FileRepository(connector)
 cache_config=cfg.redis.model_copy(update={'cache_prefix':'s37-pending-'+identity.hex})
 manager=RedisManager(cache_config); cache=RedisCacheService(manager.get_client(),cache_config)
 storage=None; owner=None; other=None; referenced_id=uuid.uuid5(identity,'reference')
 ids=[uuid.uuid5(identity,'source-'+str(index)) for index in range(131)]
 protected,active=ids[-2:]; keys=[]
 try:
  stage='isolated_storage'
  storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
   endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
   bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
   retry_attempts=1,retry_backoff=0,presign_expiry=60))
  stage='owned_fixture'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   other=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None and other is not None and owner!=other
  keys=['uploads/CHAT/pending/'+owner.hex+'/'+file_id.hex+'.png' for file_id in ids]
  for key in keys:
   await storage.upload_file(file_key=key,file_data=b'fixture')
  private='uploads/CHAT/'+identity.hex+'.png'
  await storage.upload_file(file_key=private,file_data=b'private')
  protected_key=keys[-2]; active_key=keys[-1]
  # Cross-owner legacy reference proves the guard is by key, not requesting owner.
  await repository.add_file_metadata(UserFile(id=referenced_id,user_id=other,
   type=ServiceType.CHAT,file_name=protected_key,file_url='fixture',original_name='fixture.png'))
  await cache.set_json('file_upload_admission',str(active),{'owner':str(owner)},ttl_seconds=60)
  stage='fresh_retention'
  real_now=datetime.now(UTC)
  first=await cleanup.cleanup_pending_uploads(storage=storage,repository=repository,
   cache=cache,now=real_now)
  assert first=={'status':'success','scanned':128,'deleted':0,'skipped':128,'failed':0}
  cursor=await cache.get_json('file_upload_cleanup','CHAT')
  assert cursor and cursor.get('cursor')
  stage='persisted_cursor'
  # Re-open the Redis resource: no in-memory cursor or fixture cache is used.
  await manager.close(); manager=RedisManager(cache_config)
  cache=RedisCacheService(manager.get_client(),cache_config)
  assert await cache.get_json('file_upload_cleanup','CHAT')==cursor
  # Fixture clock only; no process/provider/storage clock or deployment setting changed.
  future=real_now+timedelta(days=2)
  stage='expired_retention'
  sample=(await storage.pending_upload_page('uploads/CHAT/pending/',None,1)).objects[0]
  head=await storage.pending_upload_stat(sample.key)
  assert head.etag==sample.etag and head.size==sample.size
  assert head.modified_at.replace(microsecond=0)==sample.modified_at.replace(microsecond=0)
  counts=[]
  for _ in range(2):
   counts.append(await cleanup.cleanup_pending_uploads(storage=storage,repository=repository,
    cache=cache,now=future))
  assert sum(row['deleted'] for row in counts)==129
  assert all(row['failed']==0 and row['status']=='success' for row in counts)
  objects={row.object_name for row in storage._client.list_objects(storage._bucket,recursive=True)}
  assert objects=={protected_key,active_key,private}
  assert await storage.get_file(private)==b'private'
  assert await repository.fetch_user_file_by_id(other,referenced_id) is not None
  stage='admission_expiry_replay'
  await cache.invalidate('file_upload_admission',str(active))
  delivered=await cleanup.cleanup_pending_uploads(storage=storage,repository=repository,
   cache=cache,now=future)
  assert delivered['deleted']==1 and delivered['failed']==0
  replay=await cleanup.cleanup_pending_uploads(storage=storage,repository=repository,
   cache=cache,now=future)
  assert replay['deleted']==0 and replay['failed']==0
  objects={row.object_name for row in storage._client.list_objects(storage._bucket,recursive=True)}
  assert objects=={protected_key,private}
  return {'status':'passed','fresh_preserved':True,'expired_deleted':129,
   'private_preserved':True,'cross_owner_reference_preserved':True,
   'active_preserved':True,'cursor_reopened':True,'replay_idempotent':True}
 finally:
  failed_stage=stage; stage='fixture_cleanup'
  try:
   if owner is not None and other is not None:
    row=await repository.fetch_user_file_by_id(other,referenced_id)
    if row is not None:
     assert row.file_name==keys[-2] and row.original_name=='fixture.png'
     await repository.delete_file_metadata(user_id=other,file_id=referenced_id)
    assert await repository.fetch_user_file_by_id(other,referenced_id) is None
   for file_id in ids:
    await cache.invalidate('file_upload_admission',str(file_id))
    assert await cache.get_json('file_upload_admission',str(file_id)) is None
   await cache.invalidate('file_upload_cleanup','CHAT')
   assert await cache.get_json('file_upload_cleanup','CHAT') is None
   if storage is not None:
    allowed=set(keys)|{'uploads/CHAT/'+identity.hex+'.png'}
    for row in storage._client.list_objects(storage._bucket,recursive=True):
     assert row.object_name in allowed
     await storage.delete_file(file_key=row.object_name)
    assert not list(storage._client.list_objects(storage._bucket,recursive=True))
  finally:
   await manager.close(); await connector.close()
   if storage is not None: storage._client._http.clear()
  stage=failed_stage
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_pending_retention_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PENDING_RETENTION") != "1", reason="isolated S3, scoped dev SQL/Redis"
)
def test_isolated_s3_retention_real_sql_reference_and_redis_cursor():
    _run_minio_probe(
        real_persistence=True,
        probe=_PROBE,
        modules=_MODULES,
        expected_report={
            "status": "passed",
            "fresh_preserved": True,
            "expired_deleted": 129,
            "private_preserved": True,
            "cross_owner_reference_preserved": True,
            "active_preserved": True,
            "cursor_reopened": True,
            "replay_idempotent": True,
        },
    )
