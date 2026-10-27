"""Opt-in isolated MinIO; optional scoped real dev PostgreSQL/Redis persistence."""

import ast
import asyncio
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

import pytest

from tests.test_document_storage_process_recovery_live import _checked, _docker, _report

_MODULES = (
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/application/file_saver_service.py",
    "service/services/files/application/direct_upload.py",
    "service/services/files/persistence/file_repository.py",
    "service/infrastructure/cache/cache.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,threading,uuid,urllib.request
from pathlib import Path
logging.disable(logging.CRITICAL)
from fastapi import HTTPException
from service.settings import MinioConfig,config
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.application import direct_upload
from service.models.key_value import ServiceType
from service.services.files.persistence.file_repository import FileRepository
from service.infrastructure.cache.cache import RedisCacheService
values=json.loads(sys.stdin.read()); stage='source_parity'
class Cache:
 def __init__(self): self.values={}
 async def set_json(self,namespace,identifier,payload,ttl_seconds):
  self.values[(namespace,identifier)]=payload
 async def get_json(self,namespace,identifier): return self.values.get((namespace,identifier))
class Repository:
 def __init__(self): self.rows={}
 async def fetch_user_file_by_id(self,owner,file_id):
  row=self.rows.get(file_id)
  return row if row is not None and row.user_id==owner else None
 async def add_file_metadata(self,row):
  assert row.id not in self.rows
  self.rows[row.id]=row; return row
class SqlRepository:
 def __init__(self,repository):
  self.repository=repository; self.rows={}; self.lose_ack=False
 async def fetch_user_file_by_id(self,owner,file_id):
  row=await self.repository.fetch_user_file_by_id(owner,file_id)
  if row is not None: self.rows[row.id]=row
  return row
 async def add_file_metadata(self,row):
  saved=await self.repository.add_file_metadata(row)
  if self.lose_ack:
   self.lose_ack=False; raise OSError('synthetic acknowledgement loss')
  self.rows[saved.id]=saved; return saved
 async def add_direct_file_metadata(self,row,verify_admission):
  saved=await self.repository.add_direct_file_metadata(row,verify_admission)
  if saved is None: return None
  if self.lose_ack:
   self.lose_ack=False; raise OSError('synthetic acknowledgement loss')
  self.rows[saved.id]=saved; return saved
 async def delete_owned_file_atomically(self,owner,file_id,before_delete):
  deleted=await self.repository.delete_owned_file_atomically(owner,file_id,before_delete)
  if deleted: self.rows.pop(file_id,None)
  return deleted
 async def delete_file_metadata(self,*,user_id,file_id):
  await self.repository.delete_file_metadata(user_id=user_id,file_id=file_id)
  self.rows.pop(file_id,None)
async def main():
 global stage
 for module,expected in zip((sys.modules[MinioFileStorage.__module__],
  sys.modules[FileSaverService.__module__],direct_upload,
  sys.modules[FileRepository.__module__],sys.modules[RedisCacheService.__module__]),
  values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected
 stage='isolated_storage'
 config.file.settings.max_file_size_byte=8
 config.file.settings.allowed_extensions=['.png']
 storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
  endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
  bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
  retry_attempts=1,retry_backoff=0,presign_expiry=60))
 repository=Repository(); cache=Cache(); owner=uuid.uuid4()
 connector=None; manager=None; issued=[]; persistence=values['real_persistence']
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 async def put(offer,body):
  def send():
   request=urllib.request.Request(offer['upload_url'],data=body,method='PUT')
   with opener.open(request,timeout=10) as response: assert response.status==200
  await asyncio.to_thread(send)
 async def offer(body):
  result=await saver.presign_upload(owner,ServiceType.CHAT,'fixture.png',60)
  issued.append(result['file_id'])
  await put(result,body); return result
 async def finish(result):
  return await saver.finalize_upload(owner,ServiceType.CHAT,result['file_id'],result['file_key'])
 try:
  if persistence:
   stage='persistence_fixture'
   from sqlalchemy import text
   from service.settings import Config
   from service.infrastructure.database.postgresql import PgConnector
   from service.infrastructure.cache.manager import RedisManager
   cfg=Config(); assert cfg.pg.host=='postgres' and cfg.redis.enabled
   connector=PgConnector(cfg.pg,force_new=True)
   async with connector.get_session_context() as db:
    owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
     {'email':'s38-video-acceptance@example.com'})
    assert owner is not None
   manager=RedisManager(cfg.redis)
   cache_config=cfg.redis.model_copy(update={'cache_prefix':'s37-direct-'+values['identity']})
   cache=RedisCacheService(manager.get_client(),cache_config)
   repository=SqlRepository(FileRepository(connector))
  saver=FileSaverService(repository,'direct/'+values['identity'],storage,upload_cache=cache)
  stage='put_publish_replay'
  original=await offer(b'initial'); first=await finish(original)
  assert first['file_id']==original['file_id']
  private=repository.rows[first['file_id']].file_name
  assert private!=original['file_key']
  await put(original,b'changed')
  assert await storage.get_file(private)==b'initial'
  assert await finish(original)==first and len(repository.rows)==1
  stage='foreign_owner'
  try:
   await saver.finalize_upload(uuid.uuid4(),ServiceType.CHAT,
    original['file_id'],original['file_key'])
  except HTTPException as error: assert error.status_code==404
  else: raise AssertionError()
  stage='oversized_source'
  oversized=await offer(b'oversized')
  try: await finish(oversized)
  except HTTPException as error: assert error.status_code==503
  else: raise AssertionError()
  assert len(repository.rows)==1
  stage='conditional_copy'
  racing=await offer(b'initial'); real_copy=storage._client.copy_object
  def change_before_copy(*args,**kwargs):
   from io import BytesIO
   storage._client.put_object(storage._bucket,racing['file_key'],BytesIO(b'changed'),7)
   return real_copy(*args,**kwargs)
  storage._client.copy_object=change_before_copy
  try:
   try: await finish(racing)
   except HTTPException as error: assert error.status_code==503
   else: raise AssertionError()
   assert len(repository.rows)==1
  finally: storage._client.copy_object=real_copy
  stage='cancel_copy'
  cancelled=await offer(b'initial')
  entered,release,completed=threading.Event(),threading.Event(),threading.Event()
  def held_copy(*args,**kwargs):
   entered.set(); assert release.wait(10)
   result=real_copy(*args,**kwargs); completed.set(); return result
  storage._client.copy_object=held_copy
  task=asyncio.create_task(finish(cancelled))
  try:
   assert await asyncio.to_thread(entered.wait,3)
   task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
   assert not task.done()
   release.set()
   try: await asyncio.wait_for(task,20)
   except asyncio.CancelledError: pass
   else: raise AssertionError()
   assert completed.is_set() and len(repository.rows)==1
  finally:
   release.set(); await asyncio.gather(task,return_exceptions=True)
   storage._client.copy_object=real_copy
  stage='subsequent_recovery'
  recovered=await finish(cancelled)
  assert recovered['file_id']==cancelled['file_id'] and len(repository.rows)==2
  assert await storage.get_file(repository.rows[recovered['file_id']].file_name)==b'initial'
  if persistence:
   stage='cross_session_guard'
   actual=repository.repository
   async with connector.get_session_context() as left_db:
    async with connector.get_session_context() as right_db:
     left_pid=await left_db.scalar(text('SELECT pg_backend_pid()'))
     right_pid=await right_db.scalar(text('SELECT pg_backend_pid()'))
     assert left_pid!=right_pid
     await actual._lock_owned_file(left_db,owner,original['file_id'])
     waiting=asyncio.create_task(actual._lock_owned_file(right_db,owner,original['file_id']))
     try:
      for attempt in range(40):
       state=await left_db.scalar(text('SELECT wait_event_type FROM pg_stat_activity '
        'WHERE pid=:pid'),{'pid':right_pid})
       if state=='Lock': break
       await asyncio.sleep(0.02)
      else: raise AssertionError()
      assert not waiting.done()
      await left_db.rollback()
      await asyncio.wait_for(waiting,3)
     finally:
      if not waiting.done(): waiting.cancel()
      await asyncio.gather(waiting,return_exceptions=True)
      await left_db.rollback(); await right_db.rollback()
   stage='concurrent_database_callback'
   concurrent=await offer(b'initial')
   commit=storage.commit_presigned_upload; arrived=0; both=asyncio.Event()
   async def concurrent_commit(**kwargs):
    nonlocal arrived
    arrived+=1
    if arrived==2: both.set()
    await asyncio.wait_for(both.wait(),10)
    return await commit(**kwargs)
   storage.commit_presigned_upload=concurrent_commit
   try:
    left,right=await asyncio.gather(finish(concurrent),finish(concurrent))
    assert left==right and left['file_id']==concurrent['file_id']
   finally: storage.commit_presigned_upload=commit
   stage='database_lost_ack'
   lost=await offer(b'initial'); repository.lose_ack=True
   committed=await finish(lost)
   assert committed['file_id']==lost['file_id'] and await finish(lost)==committed
   stage='independent_persistence_read'
   async with connector.get_session_context() as db:
    rows=(await db.execute(text('SELECT id,upload_intent_id,original_name,file_name '
     'FROM profile.user_file WHERE user_id=:owner AND id=ANY(:ids)'),
     {'owner':owner,'ids':issued})).mappings().all()
    assert len(rows)==4
    for row in rows:
     assert row['id']==row['upload_intent_id'] and row['original_name']=='fixture.png'
     assert '/pending/' not in row['file_name']
     assert await storage.get_file(row['file_name'])==b'initial'
   second_cache=RedisCacheService(manager.get_client(),cache_config)
   assert await second_cache.get_json('file_upload_admission',str(lost['file_id']))
   await cache.invalidate('file_upload_admission',str(lost['file_id']))
   assert await finish(lost)==committed
   stage='deleted_upload_replay'
   # Restore a still-valid admission, then require DELETE to revoke it.
   await cache.set_json('file_upload_admission',str(lost['file_id']),
    {'owner':str(owner),'mode':'CHAT','key':lost['file_key'],'name':'fixture.png',
     'expires_at':__import__('time').time()+60},ttl_seconds=60)
   private=repository.rows[lost['file_id']].file_name
   await saver.delete(owner,lost['file_id'])
   await put(lost,b'changed')
   try: await finish(lost)
   except HTTPException as error: assert error.status_code==404
   else: raise AssertionError()
   assert await cache.get_json('file_upload_admission',str(lost['file_id'])) is None
   assert await repository.fetch_user_file_by_id(owner,lost['file_id']) is None
   assert private not in [item.object_name for item in
    storage._client.list_objects(storage._bucket,recursive=True)]
   stage='publication_delete_race'
   race=await offer(b'initial'); race_commit=storage.commit_presigned_upload
   late_started,release_late=asyncio.Event(),asyncio.Event()
   async def held_publication(**kwargs):
    await race_commit(**kwargs)
    if asyncio.current_task() is first_task:
     await asyncio.wait_for(late_started.wait(),5)
    else:
     assert asyncio.current_task() is late_task
     late_started.set(); await asyncio.wait_for(release_late.wait(),10)
   storage.commit_presigned_upload=held_publication
   first_task=asyncio.create_task(finish(race)); late_task=asyncio.create_task(finish(race))
   try:
    stage='publication_race_first_commit'
    await asyncio.wait_for(first_task,10)
    stage='publication_race_delete'
    await saver.delete(owner,race['file_id'])
    release_late.set()
    stage='publication_race_late_result'
    try: await asyncio.wait_for(late_task,10)
    except HTTPException as error: assert error.status_code==404
    else: raise AssertionError()
    stage='publication_race_final_state'
    assert await repository.fetch_user_file_by_id(owner,race['file_id']) is None
    assert await cache.get_json('file_upload_admission',str(race['file_id'])) is None
   finally:
    release_late.set(); await asyncio.gather(first_task,late_task,return_exceptions=True)
    storage.commit_presigned_upload=race_commit
  objects=list(storage._client.list_objects(storage._bucket,recursive=True))
  assert len(objects)==(10 if persistence else 6)
  report={'status':'passed','published_files':5 if persistence else 2,'replay_reused':True,
   'late_put_immutable':True,'conditional_copy_blocked':True,'oversized_blocked':True,
   'cancelled_copy_compensated':True,'subsequent_recovery':True,'source_parity':True,
   'real_persistence':persistence}
  if persistence:
   report.update(deleted_replay_blocked=True,late_publication_blocked=True,
    sql_cross_session_guard=True)
  return report
 finally:
  failed_stage=stage
  stage='cleanup'
  if connector is not None:
   try:
    if issued:
     async with connector.get_session_context() as db:
      await db.execute(text('DELETE FROM profile.user_file WHERE user_id=:owner '
       'AND id=ANY(:ids)'),{'owner':owner,'ids':issued})
      await db.commit()
      assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
       'WHERE user_id=:owner AND id=ANY(:ids)'),{'owner':owner,'ids':issued})==0
    if manager is not None:
     for file_id in issued:
      for namespace in ('file_upload_admission','file_upload_scan'):
       await cache.invalidate(namespace,str(file_id))
       assert await cache.get_json(namespace,str(file_id)) is None
   finally:
    if manager is not None: await manager.close()
    await connector._engine.dispose()
  for item in storage._client.list_objects(storage._bucket,recursive=True):
   assert item.object_name.startswith('direct/'+values['identity']+'/')
   storage._client.remove_object(storage._bucket,item.object_name)
  assert not list(storage._client.list_objects(storage._bucket,recursive=True))
  storage._client._http.clear()
  stage=failed_stage
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_direct_upload_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.asyncio
async def test_live_race_barrier_identifies_tasks_not_copy_arrival_order():
    """Redis/SQL scheduling may let the intended late callback reach copy first."""
    wrapper = next(
        node
        for node in ast.walk(ast.parse(_PROBE))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "held_publication"
    )
    # Lift the actual embedded fixture closure for deterministic local execution.
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    late_started, release_late, allow_first = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def commit(**kwargs):
        return None

    scope = {
        "asyncio": asyncio,
        "race_commit": commit,
        "late_started": late_started,
        "release_late": release_late,
    }
    exec(compile(module, "<live-race-barrier>", "exec"), scope)

    async def first():
        await allow_first.wait()
        await scope["held_publication"]()

    late_task = asyncio.create_task(scope["held_publication"]())
    first_task = asyncio.create_task(first())
    scope.update(first_task=first_task, late_task=late_task)
    try:
        # Explicitly reverse arrival; no sleep-based scheduler assumption.
        await asyncio.wait_for(late_started.wait(), 2)
        allow_first.set()
        await asyncio.wait_for(first_task, 2)
        assert not late_task.done(), "late callback escaped the intended DELETE barrier"
        release_late.set()
        await asyncio.wait_for(late_task, 2)
    finally:
        allow_first.set()
        release_late.set()
        for task in (first_task, late_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, late_task, return_exceptions=True)


@pytest.mark.skipif(os.getenv("S37_LIVE_DIRECT_UPLOAD") != "1", reason="isolated real MinIO")
def test_isolated_minio_direct_upload_admission_copy_and_cancellation():
    _run_minio_probe(real_persistence=False)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DIRECT_UPLOAD_SQL") != "1", reason="scoped dev SQL/Redis and isolated MinIO"
)
def test_direct_upload_real_sql_redis_concurrency_and_lost_ack():
    _run_minio_probe(real_persistence=True)


def _run_minio_probe(
    *,
    real_persistence: bool,
    probe=None,
    modules=None,
    expected_report=None,
    probe_timeout=60,
    probe_executor=None,
):
    assert 1 <= probe_timeout <= 240, "invalid_isolated_probe_timeout"
    identity = uuid.uuid4().hex
    name = f"gpthub-s37-direct-{identity}"
    created = False
    environment = dict(os.environ)
    environment["MINIO_ROOT_USER"] = "s37" + identity
    environment["MINIO_ROOT_PASSWORD"] = secrets.token_hex(24)
    values = {
        "identity": identity,
        "real_persistence": real_persistence,
        "endpoint": f"{name}:9000",
        "access_key": environment["MINIO_ROOT_USER"],
        "secret_key": environment["MINIO_ROOT_PASSWORD"],
        "digests": [
            hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (modules or _MODULES)
        ],
    }
    try:
        networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-backend-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        minio_networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-minio-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        shared = sorted(set(networks) & set(minio_networks))
        assert len(shared) == 1, "dev network must be unambiguous"
        image = _checked("inspect", "gpthub-dev-minio-1", "--format", "{{.Image}}")
        assert image.startswith("sha256:")
        _checked(
            "create",
            "--name",
            name,
            "--label",
            f"gpthub.s37.direct={identity}",
            "--network",
            shared[0],
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            image,
            "server",
            "/data",
            env=environment,
        )
        created = True
        _checked("start", name)
        health = (
            "import sys,time,urllib.request\n"
            "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
            "for attempt in range(30):\n"
            " try:\n"
            "  response=opener.open(sys.argv[1],timeout=1)\n"
            "  ok=response.status==200; response.close()\n"
            "  if ok: sys.exit(0)\n"
            " except Exception: pass\n"
            " time.sleep(0.5)\n"
            "sys.exit(1)"
        )
        _checked(
            "exec",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            health,
            f"http://{name}:9000/minio/health/ready",
        )
        if probe_executor is None:
            result = _docker(
                "exec",
                "-i",
                "gpthub-dev-backend-1",
                "python",
                "-c",
                probe or _PROBE,
                input=json.dumps(values).encode(),
                timeout=probe_timeout,
            )
        else:
            # Private test boundary for lifecycle handshakes; values never enter argv/logs.
            result = probe_executor(name, values, probe or _PROBE, probe_timeout)
        report = _report(result)
        assert result.returncode == 0, f"direct upload failed at {report.get('stage', 'unknown')}"
        assert report["status"] == "passed"
        if expected_report is not None:
            assert report == expected_report, "isolated probe aggregate mismatch"
            return
        assert all(
            value is True
            for key, value in report.items()
            if key not in {"status", "published_files", "real_persistence"}
        )
        assert report["published_files"] == (5 if real_persistence else 2)
        assert report["real_persistence"] is real_persistence
    finally:
        if created:
            actual = _checked(
                "inspect", name, "--format", '{{index .Config.Labels "gpthub.s37.direct"}}'
            )
            assert actual == identity
            _checked("rm", "--force", "--volumes", name)
