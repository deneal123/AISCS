"""Real broker/prefork loss at durable completed-job and audit-usage boundaries."""

import ast
import asyncio
import inspect
import json
import os
import re
import subprocess
from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_CELERY_REDELIVERY") != "1", reason="isolated dev Celery worker"
)
@pytest.mark.parametrize(
    "scenario",
    [
        "completed",
        "audit_usage",
        "prepared",
        pytest.param(
            "paid",
            marks=pytest.mark.skipif(
                os.getenv("S37_LIVE_PAID_RECOVERY") != "1",
                reason="actual metered dev provider call",
            ),
        ),
    ],
)
async def test_document_state_survives_prefork_loss_without_new_charge(scenario):
    probe = """
import asyncio,hashlib,json,logging,os,signal,subprocess,sys,time,uuid
logging.disable(logging.CRITICAL)
fixture_dir=sys.argv[1]
scenario=sys.argv[2]
sys.path.insert(0,fixture_dir)
os.environ['PYTHONPATH']=fixture_dir+os.pathsep+os.environ.get('PYTHONPATH','/dude')
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.billing.persistence.billing_repository import BillingRepository
from s37_celery_redelivery_fixture import (
 replay_completed_job,recover_audit_checkpoint,recover_prepared_result)
from s37_celery_paid_recovery_fixture import recover_paid_result
identity=uuid.uuid4().hex
queue='s37-redelivery-'+identity
hostname='s37-redelivery-'+identity+'@acceptance'
marker='s37:celery-redelivery:'+identity
worker=None; result=None; stage='fixture'; report=None
audit_fixture_id=None; prepared_fixture_id=None; reference_job=None
async def snapshot():
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  found=await db.execute(text('''SELECT j.id,j.user_id,j.payload
   FROM profile.user_launch j JOIN profile."user" u ON u.id=j.user_id
   JOIN profile.billing_events e ON e.user_id=j.user_id
    AND e.metadata->>'idempotency_key'=j.id::text AND e.event_type='usage'
   WHERE u.email=:email AND j.status=:status AND e.tokens>0
    AND j.id=COALESCE(CAST(:reference AS uuid),j.id)
   ORDER BY j.created_at DESC LIMIT 1'''),
   {'email':'s37-e2e-391e5206659a3654@example.com','status':'SUCCESS','reference':reference_job})
  row=found.mappings().first(); assert row is not None
  row=dict(row); payload=row['payload']; assert payload.get('reply')
  thread=payload.get('thread_id'); assert thread
  events=await db.scalar(text("SELECT count(*) FROM profile.billing_events "
   "WHERE user_id=:owner AND event_type='usage'"),{'owner':row['user_id']})
  messages=await db.scalar(text('''SELECT count(*) FROM profile.chat_messages m
   JOIN profile.chat_threads t ON m.thread_id=t.id WHERE t.thread_id=:thread
    AND t.user_id=:owner'''),{'thread':thread,'owner':row['user_id']})
 balance=await BillingRepository(connector).get_balance(user_id=str(row['user_id']))
 assert balance is not None
 return row,{'balance':balance,'events':events,'messages':messages}

async def create_audit_fixture(owner):
 from service.services.chat.persistence.documents import publication as jobs
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  rows=await jobs.enqueue(db,user_id=owner,thread_id='s37-audit-'+identity,
   workspace_id='s37-audit-'+identity,billing_job_id='s37-audit-'+identity,
   attach_to_latest=False,descriptors=({
    'build_id':identity,'artifact_id':identity,'role':'pdf',
    'source_digest':'a'*64,'artifact_sha256':'b'*64,'artifact_size':1,
    'filename':'s37-audit-fixture.pdf','mime_type':'application/pdf'},))
  audit_id=rows[0]['id']
  # The main publication workers must never claim this synthetic fixture.
  await db.execute(text('UPDATE profile.document_publication_job SET status=:state WHERE id=:id'),
   {'id':audit_id,'state':'terminal'})
  await db.commit()
  return str(audit_id)

async def remove_audit_fixture():
 if audit_fixture_id is None: return
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  await db.execute(text('DELETE FROM profile.document_publication_job '
   'WHERE id=:id AND workspace_id=:workspace AND status=:state'),
   {'id':uuid.UUID(audit_fixture_id),'workspace':'s37-audit-'+identity,'state':'terminal'})
  await db.commit()
  assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job WHERE id=:id'),
   {'id':uuid.UUID(audit_fixture_id)})==0
  assert await db.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
   'WHERE publication_job_id=:id'),{'id':uuid.UUID(audit_fixture_id)})==0

async def create_prepared_fixture(owner):
 from service.models.db.db_models import UserLaunch
 from service.models.key_value import ProcessingStatus,ServiceType
 connector=PgConnector(Config().pg); job=uuid.uuid4()
 async with connector.get_session_context() as db:
  db.add(UserLaunch(id=job,user_id=owner,type=ServiceType.CHAT,
   status=ProcessingStatus.PROCESSING,payload={'thread_id':str(uuid.UUID(identity)),
    'acceptance_fixture':'s37-paid-recovery' if scenario=='paid' else 's37-prepared-celery'}))
  await db.commit()
 return str(job)

async def check_prepared_result(owner):
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  saved=await db.execute(text('SELECT status,payload FROM profile.user_launch '
   'WHERE id=:id AND user_id=:owner'),{'id':uuid.UUID(prepared_fixture_id),'owner':owner})
  saved=saved.mappings().one()
  assert saved['status']=='SUCCESS' and '_prepared_turn_v1' not in saved['payload']
  if scenario=='paid':
   assert saved['payload']['metadata']['usage']['total']>0
  else:
   assert saved['payload']['reply']=='synthetic prepared result'
   assert saved['payload']['metadata']['usage']['total']==33
  messages=await db.scalar(text('SELECT count(*) FROM profile.chat_messages m '
   'JOIN profile.chat_threads t ON t.id=m.thread_id '
   'WHERE t.thread_id=:thread AND t.user_id=:owner'),
   {'thread':str(uuid.UUID(identity)),'owner':owner})
  assert messages==2
  events=await db.execute(text('SELECT tokens,metadata FROM profile.billing_events '
   "WHERE user_id=:owner AND metadata->>'idempotency_key'=:job"),
   {'job':prepared_fixture_id,'owner':owner})
  events=list(events.mappings())
  if scenario=='paid':
   assert len(events)==1 and events[0]['tokens']>0
   meta=events[0]['metadata']
   debit=int(meta.get('from_subscription') or 0)+int(meta.get('from_topup') or 0)
   assert debit>0 and meta.get('per_call')
   assert saved['payload']['metadata']['usage']['credits']==debit
   assert saved['payload']['metadata']['usage']['total']==events[0]['tokens']
   return debit
  assert len(events)==0

async def cleanup_workspace(owner):
 if scenario!='paid' or prepared_fixture_id is None: return
 from service.infrastructure import workspace_client as workspace
 store=celery_app.backend.client; thread=str(uuid.UUID(identity))
 ref=await workspace.read_binding(store,thread)
 if ref is not None:
  assert str(ref['user_id'])==str(owner)
  await workspace.release_workspace(store,thread)
  assert await workspace.read_binding(store,thread) is None
  try: await workspace.tree(ref)
  except workspace.WorkspaceGone: pass
  else: raise RuntimeError('acceptance_workspace_not_removed')

async def remove_prepared_fixture(owner):
 if prepared_fixture_id is None: return
 connector=PgConnector(Config().pg); thread=str(uuid.UUID(identity))
 async with connector.get_session_context() as db:
  await db.execute(text('DELETE FROM profile.chat_messages WHERE thread_id IN '
   '(SELECT id FROM profile.chat_threads WHERE thread_id=:thread AND user_id=:owner)'),
   {'thread':thread,'owner':owner})
  await db.execute(text('DELETE FROM profile.chat_threads '
   'WHERE thread_id=:thread AND user_id=:owner'),
   {'thread':thread,'owner':owner})
  await db.execute(text('DELETE FROM profile.user_launch WHERE id=:id AND user_id=:owner '
   "AND payload->>'thread_id'=:thread"),
   {'id':uuid.UUID(prepared_fixture_id),'owner':owner,'thread':thread})
  await db.commit()
  assert await db.scalar(text('SELECT count(*) FROM profile.user_launch WHERE id=:id'),
   {'id':uuid.UUID(prepared_fixture_id)})==0
  assert await db.scalar(text('SELECT count(*) FROM profile.chat_threads WHERE thread_id=:thread'),
   {'thread':thread})==0
def stop_worker():
 if worker is not None and worker.poll() is None:
  os.killpg(worker.pid,signal.SIGTERM)
  try: worker.wait(timeout=15)
  except subprocess.TimeoutExpired:
   os.killpg(worker.pid,signal.SIGKILL); worker.wait(timeout=10)
try:
 row,before=asyncio.run(snapshot()); payload=row['payload']; reference_job=row['id']
 if scenario=='audit_usage': audit_fixture_id=asyncio.run(create_audit_fixture(row['user_id']))
 if scenario in ('prepared','paid'):
  prepared_fixture_id=asyncio.run(create_prepared_fixture(row['user_id']))
 stage='worker_start'
 worker=subprocess.Popen([sys.executable,'-m','celery','-A',
  'service.infrastructure.messaging.celery_app','worker','--pool=prefork',
  '--concurrency=1','--queues='+queue,'--hostname='+hostname,
  '--include=s37_celery_redelivery_fixture,s37_celery_paid_recovery_fixture','--loglevel=WARNING',
  '--without-gossip','--without-mingle','--without-heartbeat'],
  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 deadline=time.monotonic()+60
 while True:
  assert worker.poll() is None,'acceptance_worker_stopped'
  replies=celery_app.control.ping(destination=[hostname],timeout=1)
  if replies: break
  assert time.monotonic()<deadline,'acceptance_worker_start_timeout'
  time.sleep(0.5)
 if scenario=='audit_usage':
  result=recover_audit_checkpoint.apply_async(queue=queue,kwargs={
   'marker':marker,'publication_id':audit_fixture_id,'owner':str(row['user_id'])})
 elif scenario in ('prepared','paid'):
  task=recover_paid_result if scenario=='paid' else recover_prepared_result
  result=task.apply_async(queue=queue,kwargs={
   'marker':marker,'job_id':prepared_fixture_id,'thread_id':str(uuid.UUID(identity)),
   'owner':str(row['user_id'])})
 else:
  result=replay_completed_job.apply_async(queue=queue,kwargs={
   'marker':marker,'job_id':str(row['id']),'thread_id':payload['thread_id'],
   'owner':str(row['user_id']),
   'reply_digest':hashlib.sha256(payload['reply'].encode()).hexdigest()})
 stage='redelivery'
 outcome=result.get(timeout=240 if scenario=='paid' else 90,propagate=False)
 assert isinstance(outcome,dict) and outcome=={
  'status':{'audit_usage':'audit_recovered','prepared':'prepared_recovered',
   'paid':'paid_recovered','completed':'reused'}[scenario],
  'attempts':2,'broker_redelivered':True,'prefork_changed':True}
 assert int(celery_app.backend.client.get(marker))==2
 _,after=asyncio.run(snapshot())
 stage='accounting'
 if scenario=='paid':
  debit=asyncio.run(check_prepared_result(row['user_id']))
  assert after['events']==before['events']+1 and after['messages']==before['messages']
  assert after['balance']['used']-before['balance']['used'] + \
   before['balance']['topup']-after['balance']['topup']==debit
 else: assert before==after
 if scenario=='prepared': asyncio.run(check_prepared_result(row['user_id']))
 report={'prefork_loss':True,'redelivered':True,'attempts':2,
  'balance_unchanged':True,'usage_events_unchanged':True,'messages_unchanged':True}
 if scenario=='paid':
  report={'prefork_loss':True,'redelivered':True,'attempts':2,
   'single_actual_charge':True,'no_second_agent_call':True,'one_message_pair':True}
except Exception:
 report={'status':'failed','stage':stage}
finally:
 try:
  stage='worker_cleanup'; stop_worker()
  if worker is not None: assert worker.poll() is not None
  stage='redis_cleanup'
  if result is not None:
   result.forget()
   assert not celery_app.backend.client.exists(celery_app.backend.get_key_for_task(result.id))
  suffixes=('',':first-pid',':audit-id',':settlements',':provider-calls',':agent-calls',
   ':charge-calls',':first-debit',':recovery-debit',':reply-digest',':model',':tokens',':receipts')
  keys=tuple(marker+suffix for suffix in suffixes)
  celery_app.backend.client.delete(*keys)
  assert not celery_app.backend.client.exists(*keys)
  stage='audit_cleanup'; asyncio.run(remove_audit_fixture())
  stage='workspace_cleanup'; asyncio.run(cleanup_workspace(row['user_id']))
  stage='prepared_cleanup'; asyncio.run(remove_prepared_fixture(row['user_id']))
  stage='queue_cleanup'
  with celery_app.connection_for_write() as connection:
   temporary=connection.SimpleQueue(queue)
   temporary.queue.delete(if_unused=False,if_empty=False)
   temporary.close()
  with celery_app.connection_for_write() as connection:
   try:
    connection.default_channel.queue_declare(queue=queue,passive=True)
   except Exception as missing:
    assert str(getattr(missing,'reply_code',None))=='404'
   else:
    raise RuntimeError('acceptance_queue_not_removed')
 except Exception:
  report={'status':'failed','stage':stage}
print(json.dumps(report))
if report.get('status')=='failed': raise SystemExit(1)
"""
    temporary = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "gpthub-dev-backend-1", "mktemp", "-d", "/tmp/s37-celery-XXXXXXXX"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    fixture_dir = temporary.stdout.decode().strip()
    if temporary.returncode != 0 or not re.fullmatch(
        r"/tmp/s37-celery-[A-Za-z0-9]{8}", fixture_dir
    ):
        pytest.fail("celery_fixture_directory_failed")
    try:
        for name in ("celery_redelivery_fixture", "celery_paid_recovery_fixture"):
            copied = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "cp",
                    str(Path(__file__).with_name(name + ".py")),
                    "gpthub-dev-backend-1:" + fixture_dir + "/s37_" + name + ".py",
                ],
                capture_output=True,
                timeout=15,
                check=False,
            )
            if copied.returncode != 0:
                pytest.fail("celery_fixture_copy_failed")
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-", fixture_dir, scenario],
            input=probe.encode(),
            capture_output=True,
            timeout=430 if scenario == "paid" else 190,
            check=False,
        )
    finally:
        cleanup = await asyncio.to_thread(
            subprocess.run,
            ["docker", "exec", "gpthub-dev-backend-1", "rm", "-r", "--", fixture_dir],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if cleanup.returncode != 0:
            pytest.fail("celery_fixture_cleanup_failed")
        absent = await asyncio.to_thread(
            subprocess.run,
            ["docker", "exec", "gpthub-dev-backend-1", "test", "!", "-e", fixture_dir],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if absent.returncode != 0:
            pytest.fail("celery_fixture_directory_remains")
    if result.returncode != 0:
        stage = "unknown"
        try:
            report = json.loads(result.stdout)
            if report.get("stage") in {
                "fixture",
                "worker_start",
                "redelivery",
                "accounting",
                "worker_cleanup",
                "redis_cleanup",
                "audit_cleanup",
                "prepared_cleanup",
                "workspace_cleanup",
                "queue_cleanup",
            }:
                stage = report["stage"]
        except (ValueError, AttributeError):
            pass
        pytest.fail("celery_redelivery_acceptance_failed:" + stage)
    expected = {
        "prefork_loss": True,
        "redelivered": True,
        "attempts": 2,
        "balance_unchanged": True,
        "usage_events_unchanged": True,
        "messages_unchanged": True,
    }
    if scenario == "paid":
        expected = {
            "prefork_loss": True,
            "redelivered": True,
            "attempts": 2,
            "single_actual_charge": True,
            "no_second_agent_call": True,
            "one_message_pair": True,
        }
    assert json.loads(result.stdout) == expected


def test_celery_redelivery_probe_compiles_without_live_execution():
    source = ast.parse(
        inspect.getsource(test_document_state_survives_prefork_loss_without_new_charge)
    )
    probe = next(
        node.value.value
        for node in ast.walk(source)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and any(isinstance(target, ast.Name) and target.id == "probe" for target in node.targets)
    )
    compile(probe, "celery-redelivery-probe", "exec")
    compile(
        Path(__file__).with_name("celery_paid_recovery_fixture.py").read_text(encoding="utf-8"),
        "celery-paid-recovery-fixture",
        "exec",
    )
