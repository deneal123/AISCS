"""Native task on real broker and isolated prefork generations; no shared S3 sweep."""

import ast
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.test_direct_upload_live import _run_minio_probe
from tests.test_pending_upload_cleanup_live import _MODULES as _RETENTION_MODULES

_MODULES = (
    *_RETENTION_MODULES,
    "service/services/files/infrastructure/maintenance.py",
    "service/infrastructure/messaging/celery_app.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,os,signal,subprocess,sys,time,uuid
from datetime import timedelta
from pathlib import Path
logging.disable(logging.CRITICAL)
from service.settings import Config,MinioConfig
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.persistence.file_repository import FileRepository
from service.services.files.application import pending_upload_cleanup as cleanup
from service.services.files.domain import pending_upload as inventory
from service.infrastructure.cache.cache import RedisCacheService
from service.infrastructure.cache.manager import RedisManager
from service.services.files.infrastructure import maintenance
from service.infrastructure.messaging.celery_app import celery_app as app
app_module=sys.modules['service.infrastructure.messaging.celery_app']
values=json.loads(sys.stdin.read()); identity=uuid.UUID(values['identity']); stage='source_parity'
queue='s37-pending-'+identity.hex; hostname=queue+'@acceptance'
worker=None; storage=None; manager=None; results=[]; cache=None
loop=asyncio.new_event_loop()
key='uploads/CHAT/pending/'+identity.hex+'/'+uuid.uuid5(identity,'source').hex+'.png'
private='uploads/CHAT/'+identity.hex+'.png'
worker_code=r'''
import logging,os
logging.disable(logging.CRITICAL)
from service.settings import Config
c=Config()
# Fail closed before importing/starting the consumer. Deployment secrets are not changed.
assert c.storage.backend=='minio'
assert c.minio.endpoint==os.environ['S37_EXPECTED_ENDPOINT']
assert c.minio.access_key==os.environ['MINIO__ACCESS_KEY']
assert c.minio.secret_key==os.environ['MINIO__SECRET_KEY']
assert c.minio.bucket=='acceptance' and c.minio.public_endpoint=='' and not c.minio.secure
assert c.redis.cache_prefix==os.environ['S37_EXPECTED_PREFIX']
from service.infrastructure.messaging.celery_app import celery_app
celery_app.worker_main(['worker','--pool=prefork','--concurrency=1',
 '--queues='+os.environ['S37_QUEUE'],'--hostname='+os.environ['S37_HOSTNAME'],
 '--loglevel=WARNING','--without-gossip','--without-mingle','--without-heartbeat'])
'''
def stop():
 global worker
 if worker is not None and worker.poll() is None:
  os.killpg(worker.pid,signal.SIGTERM)
  try: worker.wait(timeout=15)
  except subprocess.TimeoutExpired:
   os.killpg(worker.pid,signal.SIGKILL); worker.wait(timeout=10)
 assert worker is None or worker.poll() is not None
def start(environment):
 global worker
 worker=subprocess.Popen([sys.executable,'-c',worker_code],env=environment,
  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 deadline=time.monotonic()+35
 while not app.control.ping(destination=[hostname],timeout=1):
  assert worker.poll() is None and time.monotonic()<deadline
  time.sleep(.25)
 stats=app.control.inspect(destination=[hostname],timeout=2).stats()
 pids=stats[hostname]['pool']['processes']
 assert len(pids)==1 and isinstance(pids[0],int)
 return worker.pid,pids[0]
async def prepare():
 global storage,manager,cache
 cfg=Config(); assert cfg.pg.host=='postgres'
 redis_cfg=cfg.redis.model_copy(update={'cache_prefix':queue})
 manager=RedisManager(redis_cfg); cache=RedisCacheService(manager.get_client(),redis_cfg)
 storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
  endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
  bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
  retry_attempts=1,retry_backoff=0,presign_expiry=60))
 await storage.upload_file(file_key=key,file_data=b'pending')
 await storage.upload_file(file_key=private,file_data=b'private')
async def check():
 assert await storage.get_file(key)==b'pending'
 assert await storage.get_file(private)==b'private'
 assert await cache.get_json('file_upload_cleanup','CHAT')=={'cursor':None}
async def cleanup_fixture():
 if cache is not None:
  await cache.invalidate('file_upload_cleanup','CHAT')
  assert await cache.get_json('file_upload_cleanup','CHAT') is None
 if storage is not None:
  for item in storage._client.list_objects(storage._bucket,recursive=True):
   assert item.object_name in {key,private}
   await storage.delete_file(file_key=item.object_name)
  assert not list(storage._client.list_objects(storage._bucket,recursive=True))
 if manager is not None: await manager.close()
 if storage is not None: storage._client._http.clear()
def finalize_probe(report,steps):
 failures=[]
 for name,operation in steps:
  try: operation()
  except BaseException: failures.append(name)
 if failures:
  if report['status']=='passed': report={'status':'failed','stage':'fixture_cleanup'}
  report={**report,'cleanup_failures':failures}
 return report
def forget_results():
 for result in results:
  result.forget()
  assert not app.backend.client.exists(app.backend.get_key_for_task(result.id))
def remove_broker_fixture():
 from kombu import Exchange,Queue
 with app.connection_for_write() as connection:
  global stage
  stage='broker_declare'
  channel=connection.default_channel
  # Redis may have no list key after the last message. Declare only our owned
  # empty queue/binding so deletion also has the virtual channel routing state.
  owned=Queue(queue,exchange=Exchange(queue,type='direct'),routing_key=queue)(channel)
  owned.declare()
  declaration=channel.queue_declare(queue)
  stage='broker_drained'
  assert declaration[1]==0 and declaration[2]==0
  stage='broker_queue_delete'
  owned.delete(if_unused=True,if_empty=True)
  stage='broker_exchange_delete'
  owned.exchange.delete(if_unused=True)
  if connection.transport.driver_type=='redis': assert not channel.get_table(queue)
report={'status':'failed','stage':stage}
try:
 modules=(sys.modules[MinioFileStorage.__module__],sys.modules[FileRepository.__module__],
  cleanup,inventory,sys.modules[RedisCacheService.__module__],maintenance,app_module)
 for module,digest in zip(modules,values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 stage='fixture_prepare'; loop.run_until_complete(prepare())
 environment=dict(os.environ)
 environment.update({'STORAGE__BACKEND':'minio','MINIO__ENDPOINT':values['endpoint'],
  'MINIO__ACCESS_KEY':values['access_key'],'MINIO__SECRET_KEY':values['secret_key'],
  'MINIO__BUCKET':'acceptance','MINIO__PUBLIC_ENDPOINT':'','MINIO__SECURE':'false',
  'REDIS__CACHE_PREFIX':queue,'S37_EXPECTED_ENDPOINT':values['endpoint'],
  'S37_EXPECTED_PREFIX':queue,'S37_QUEUE':queue,'S37_HOSTNAME':hostname})
 expected={'status':'success','scanned':1,'deleted':0,'skipped':1,'failed':0}
 stage='first_worker_start'; first=start(environment)
 name='service.services.files.infrastructure.maintenance.cleanup_pending_uploads'
 stage='first_delivery'
 result=app.send_task(name,queue=queue,task_id=str(uuid.uuid5(identity,'task-1')))
 results.append(result); assert result.get(timeout=35)==expected
 loop.run_until_complete(check()); stage='worker_restart'; stop()
 second=start(environment); assert first[0]!=second[0] and first[1]!=second[1]
 # An accepted task result survives consumer restart, without another invocation.
 assert results[0].get(timeout=5)==expected
 stage='second_delivery'
 result=app.send_task(name,queue=queue,task_id=str(uuid.uuid5(identity,'task-2')))
 results.append(result); assert result.get(timeout=35)==expected
 loop.run_until_complete(check())
 stage='beat_scheduling'
 from celery.beat import Scheduler
 spec=dict(app.conf.beat_schedule['cleanup-pending-uploads'])
 assert spec['task']==name and spec['schedule']==3600.0
 spec['options']={'queue':queue,'task_id':str(uuid.uuid5(identity,'beat-task'))}
 # Parent probe only: allow exactly one native schedule and route it to the fixture queue.
 # No deployed Beat configuration or shared process settings are modified.
 app.conf.beat_schedule={'cleanup-pending-uploads':spec}
 class ObservedScheduler(Scheduler):
  def apply_async(self,entry,*args,**kwargs):
   receipt=super().apply_async(entry,*args,**kwargs)
   results.append(receipt); return receipt
 scheduler=ObservedScheduler(app=app)
 assert set(scheduler.schedule)=={'cleanup-pending-uploads'}
 scheduler.schedule['cleanup-pending-uploads'].last_run_at=app.now()-timedelta(hours=2)
 scheduler.tick(); assert len(results)==3
 assert results[-1].get(timeout=35)==expected
 loop.run_until_complete(check()); scheduler.close()
 report={'status':'passed','native_task_delivered':True,'prefork_restarted':True,
  'result_survived_restart':True,'cursor_persisted':True,'fresh_and_private_preserved':True,
  'native_schedule_delivered':True}
except BaseException:
 report={'status':'failed','stage':stage}
finally:
 report=finalize_probe(report,(
  ('worker',stop),('results',forget_results),('broker',remove_broker_fixture),
  ('storage_cache',lambda:loop.run_until_complete(cleanup_fixture())),
 ))
 if 'broker' in report.get('cleanup_failures',[]): report['cleanup_stage']=stage
 loop.close()
print(json.dumps(report))
if report['status']!='passed': raise SystemExit(1)
"""


def test_pending_worker_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.parametrize("initial_status", ["passed", "failed"])
def test_probe_cleanup_preserves_primary_failure_and_attempts_every_resource(initial_status):
    node = next(
        item
        for item in ast.walk(ast.parse(_PROBE))
        if isinstance(item, ast.FunctionDef) and item.name == "finalize_probe"
    )
    scope = {}
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, "<probe-cleanup>", "exec"), scope)
    observed = []

    def fail():
        observed.append("worker")
        raise RuntimeError("private_exception_marker")

    report = {"status": initial_status, "stage": "beat_scheduling"}
    result = scope["finalize_probe"](
        report, (("worker", fail), ("broker", lambda: observed.append("broker")))
    )
    assert observed == ["worker", "broker"]
    assert result == {
        "status": "failed",
        "stage": "beat_scheduling" if initial_status == "failed" else "fixture_cleanup",
        "cleanup_failures": ["worker"],
    }
    assert "private_exception_marker" not in repr(result)


def test_empty_virtual_broker_queue_does_not_require_a_redis_list_key():
    from kombu import Connection

    node = next(
        item
        for item in ast.walk(ast.parse(_PROBE))
        if isinstance(item, ast.FunctionDef) and item.name == "remove_broker_fixture"
    )
    connection = Connection("memory://")
    channel = connection.default_channel
    broker_state = channel.state
    name = "s37-pending-isolated-unit"
    scope = {
        "app": SimpleNamespace(connection_for_write=lambda: connection),
        "queue": name,
    }
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, "<probe-broker-cleanup>", "exec"), scope)
    # Redis removes the list key when the last message is consumed. A passive
    # declare then reports 404 even though the exchange binding still exists.
    with patch.object(channel, "_has_queue", return_value=False):
        scope["remove_broker_fixture"]()
    assert name not in broker_state.exchanges
    assert not list(broker_state.queue_bindings(name))


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PENDING_CELERY") != "1", reason="isolated S3/native queue and prefork"
)
def test_native_retention_task_delivered_after_isolated_worker_restart():
    _run_minio_probe(
        real_persistence=True,
        probe=_PROBE,
        modules=_MODULES,
        probe_timeout=200,
        expected_report={
            "status": "passed",
            "native_task_delivered": True,
            "prefork_restarted": True,
            "result_survived_restart": True,
            "cursor_persisted": True,
            "fresh_and_private_preserved": True,
            "native_schedule_delivered": True,
        },
    )
