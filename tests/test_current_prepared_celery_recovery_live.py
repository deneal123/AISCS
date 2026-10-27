"""Fresh isolated owner: actual prefork loss/redelivery, scripted inference and settlement."""

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/services/chat/infrastructure/chat_worker/results/prepared.py",
    "service/services/chat/infrastructure/chat_worker/execution/run.py",
    "service/services/chat/infrastructure/chat_worker/results/persistence.py",
    "service/services/chat/infrastructure/chat_worker/results/preparation.py",
    "service/services/chat/infrastructure/chat_worker/billing/charging.py",
    "service/services/chat/infrastructure/chat_worker/billing/quote.py",
    "service/services/jobs/persistence/job_repository.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,os,signal,subprocess,sys,time,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
wire=json.load(sys.stdin);folder=sys.argv[1];sys.path.insert(0,folder)
os.environ['PYTHONPATH']=folder+os.pathsep+os.environ.get('PYTHONPATH','/dude')
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.chat.infrastructure.chat_worker.results import prepared as prepared_results
from service.services.chat.infrastructure.chat_worker.results import persistence as turn_persistence
from service.services.chat.infrastructure.chat_worker.results import preparation as turn_preparation
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.billing import charging,quote
from service.services.jobs.persistence import job_repository
from service.services.chat.infrastructure import chat_worker_tasks as facade
from s37_celery_redelivery_fixture import recover_prepared_result,ForbiddenProvider
identity=uuid.uuid4().hex;marker='s37:celery-redelivery:'+identity
queue='s37-current-prepared-'+identity;hostname=queue+'@acceptance'
owner=uuid.uuid4();email='s37-current-prepared-'+owner.hex+'@fixture.invalid'
thread=str(uuid.UUID(identity));job=uuid.uuid4();worker=None;result=None;stage='source_parity'
async def create():
 cfg=Config();assert cfg.pg.host=='postgres';db=PgConnector(cfg.pg,force_new=True)
 try:
  async with db.get_session_context() as s:
   await s.execute(text('''INSERT INTO profile."user"
    (id,email,password_hash,available_launches,is_active,is_admin,topup_credit_balance)
    VALUES (:owner,:email,'!',0,false,false,0)'''),{'owner':owner,'email':email})
   await s.execute(text('''INSERT INTO profile.user_launch (id,user_id,type,status,payload)
    VALUES (:job,:owner,'CHAT','PROCESSING',CAST(:payload AS jsonb))'''),
    {'job':job,'owner':owner,'payload':json.dumps({'thread_id':thread,
     'acceptance_fixture':marker})})
   await s.commit()
 finally:await db.close()
async def verify():
 db=PgConnector(Config().pg,force_new=True)
 try:
  async with db.get_session_context() as s:
   row=(await s.execute(text('''SELECT status,payload FROM profile.user_launch
    WHERE id=:job AND user_id=:owner'''),{'job':job,'owner':owner})).mappings().one()
   assert row['status']=='SUCCESS'
   assert row['payload']['reply']=='synthetic prepared result'
   assert not any(key in row['payload'] for key in ('_accepted_turn_v1','_prepared_turn_v1'))
   messages=(await s.execute(text('''SELECT m.sender,m.content FROM profile.chat_messages m
    JOIN profile.chat_threads t ON t.id=m.thread_id
    WHERE t.thread_id=:thread AND t.user_id=:owner ORDER BY m.created_at'''),
    {'thread':thread,'owner':owner})).all()
   assert len(messages)==2 and sorted(row[0] for row in messages)==['assistant','user']
   assert next(row[1] for row in messages if row[0]=='assistant')=='synthetic prepared result'
   for table in ('billing_events','token_reservations','token_quotas','usage_daily'):
    assert await s.scalar(text('SELECT count(*) FROM profile.'+table+' WHERE user_id=:owner'),
     {'owner':owner})==0
   return hashlib.sha256(json.dumps(dict(row),sort_keys=True,default=str).encode()).hexdigest()
 finally:await db.close()
async def replay():
 return await facade.process_agent_message_async(job_id=str(job),thread_id=thread,
  user_id=str(owner),text='synthetic-prepared',memory_enabled=False,
  agent_execution=ForbiddenProvider())
async def cleanup():
 db=PgConnector(Config().pg,force_new=True)
 try:
  async with db.get_session_context() as s:
   stored=await s.scalar(text('SELECT email FROM profile."user" WHERE id=:owner'),{'owner':owner})
   if stored is not None:
    assert stored==email
    await s.execute(text('''DELETE FROM profile.chat_messages WHERE thread_id IN
     (SELECT id FROM profile.chat_threads WHERE thread_id=:thread AND user_id=:owner)'''),
     {'thread':thread,'owner':owner})
    await s.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:thread '
     'AND user_id=:owner'),
     {'thread':thread,'owner':owner})
    await s.execute(text('''DELETE FROM profile.user_launch WHERE id=:job AND user_id=:owner
     AND payload->>'thread_id'=:thread'''),{'job':job,'owner':owner,'thread':thread})
    await s.execute(text('DELETE FROM profile."user" WHERE id=:owner AND email=:email'),
     {'owner':owner,'email':email});await s.commit()
   assert await s.scalar(text('SELECT count(*) FROM profile."user" WHERE id=:owner'),
    {'owner':owner})==0
   assert await s.scalar(text('SELECT count(*) FROM profile.user_launch WHERE id=:job'),
    {'job':job})==0
   assert await s.scalar(text('SELECT count(*) FROM profile.chat_threads WHERE thread_id=:thread'),
    {'thread':thread})==0
 finally:await db.close()
try:
 for module,digest in zip((prepared_results,run_execution,turn_persistence,
  turn_preparation,charging,quote,job_repository),
  wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 fixture_digest=hashlib.sha256(Path(folder,'s37_celery_redelivery_fixture.py').read_bytes()).hexdigest()
 assert fixture_digest==wire['fixture_digest']
 stage='fixture';asyncio.run(create());stage='worker_start'
 worker=subprocess.Popen([sys.executable,'-m','celery','-A',
  'service.infrastructure.messaging.celery_app','worker','--pool=prefork','--concurrency=1',
  '--queues='+queue,'--hostname='+hostname,'--include=s37_celery_redelivery_fixture',
  '--loglevel=WARNING','--without-gossip','--without-mingle','--without-heartbeat'],
  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 deadline=time.monotonic()+45
 while not celery_app.control.ping(destination=[hostname],timeout=1):
  assert worker.poll() is None and time.monotonic()<deadline;time.sleep(.5)
 stage='redelivery'
 result=recover_prepared_result.apply_async(queue=queue,kwargs={
  'marker':marker,'job_id':str(job),'thread_id':thread,'owner':str(owner)})
 outcome=result.get(timeout=100,propagate=False)
 assert outcome=={'status':'prepared_recovered','attempts':2,
  'broker_redelivered':True,'prefork_changed':True}
 stage='persistence';before=asyncio.run(verify())
 stage='completed_replay';again=asyncio.run(replay())
 assert again['status']=='success' and again['reply']=='synthetic prepared result'
 assert asyncio.run(verify())==before
 assert int(celery_app.backend.client.get(marker+':provider-calls'))==1
 assert int(celery_app.backend.client.get(marker+':settlements'))==1
 report={'status':'passed','prefork_loss':True,'redelivered':True,'one_message_pair':True,
  'completed_replay_unchanged':True,'scripted_executions':1,'model_calls':0,'charges':0}
except BaseException:report={'status':'failed','stage':stage}
finally:
 try:
  stage='cleanup_worker'
  if worker is not None and worker.poll() is None:
   os.killpg(worker.pid,signal.SIGTERM)
   try:worker.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(worker.pid,signal.SIGKILL);worker.wait(timeout=10)
  if worker is not None:assert worker.poll() is not None
  store=celery_app.backend.client
  stage='cleanup_result'
  if result is not None:
   result.forget();assert not store.exists(celery_app.backend.get_key_for_task(result.id))
  keys=tuple(marker+suffix for suffix in ('',':first-pid',':provider-calls',':settlements'))
  stage='cleanup_keys'
  store.delete(*keys);assert not store.exists(*keys)
  stage='cleanup_queue'
  with celery_app.connection_for_write() as connection:
   temporary=connection.SimpleQueue(queue);temporary.queue.delete(if_unused=False,if_empty=False)
   temporary.close()
  with celery_app.connection_for_write() as connection:
   try:connection.default_channel.queue_declare(queue=queue,passive=True)
   except Exception as missing:assert str(getattr(missing,'reply_code',None))=='404'
   else:raise AssertionError
  store.delete('_kombu.binding.'+queue)
 except BaseException:report={'status':'failed','stage':stage}
 finally:
  try:asyncio.run(cleanup())
  except BaseException:report={'status':'failed','stage':'cleanup_sql'}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_current_celery_recovery_fixture_compiles():
    ast.parse(_PROBE)
    ast.parse(Path(__file__).with_name("celery_redelivery_fixture.py").read_text("utf-8"))


@pytest.mark.skipif(
    os.getenv("S37_LIVE_CURRENT_PREPARED_CELERY") != "1",
    reason="isolated inactive-owner prefork fixture",
)
def test_current_owned_prepared_result_survives_prefork_loss():
    container = "gpthub-dev-backend-1"
    made = subprocess.run(
        ["docker", "exec", container, "mktemp", "-d", "/tmp/s37-current-prepared-XXXXXXXX"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    folder = made.stdout.decode().strip()
    assert made.returncode == 0 and re.fullmatch(
        r"/tmp/s37-current-prepared-[A-Za-z0-9]{8}", folder
    )
    fixture = Path(__file__).with_name("celery_redelivery_fixture.py")
    try:
        copied = subprocess.run(
            [
                "docker",
                "cp",
                str(fixture),
                container + ":" + folder + "/s37_celery_redelivery_fixture.py",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert copied.returncode == 0, "current_prepared_fixture_copy_failed"
        result = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-c", _PROBE, folder],
            input=json.dumps(
                {
                    "digests": [
                        hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES
                    ],
                    "fixture_digest": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                }
            ).encode(),
            capture_output=True,
            timeout=190,
            check=False,
        )
    finally:
        removed = subprocess.run(
            ["docker", "exec", container, "rm", "-r", "--", folder],
            capture_output=True,
            timeout=15,
            check=False,
        )
        absent = subprocess.run(
            ["docker", "exec", container, "test", "!", "-e", folder],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert removed.returncode == absent.returncode == 0, (
            "current_prepared_directory_not_removed"
        )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("current_prepared_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {
            "source_parity",
            "fixture",
            "worker_start",
            "redelivery",
            "persistence",
            "completed_replay",
            "cleanup",
            "cleanup_worker",
            "cleanup_result",
            "cleanup_keys",
            "cleanup_queue",
            "cleanup_sql",
        }:
            stage = "unknown"
        pytest.fail("current_prepared_probe_failed:" + stage)
    assert report == {
        "status": "passed",
        "prefork_loss": True,
        "redelivered": True,
        "one_message_pair": True,
        "completed_replay_unchanged": True,
        "scripted_executions": 1,
        "model_calls": 0,
        "charges": 0,
    }
