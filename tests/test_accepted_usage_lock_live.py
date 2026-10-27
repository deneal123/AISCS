"""Actual PostgreSQL accepted/journal ordering; exact fixture cleanup, no billing."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,inspect,json,logging,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
from sqlalchemy import select,text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus,ServiceType
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.chat.infrastructure.chat_worker.results.accepted import (
 accepted_turn,stage_accepted)
from service.services.chat.infrastructure.chat_worker.billing.accepted_accounting import (
 lock_acceptance_accounting)
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
 MaterializationPlan,stage_materialization)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
 stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
 PreparedCheckpointInvalid,store_prepared_turn)
stage='freshness'; jobs=[]; owner=None; nonce=str(uuid.uuid4()); pending=None
async def main():
 global stage,owner,pending
 for function,expected in ((stage_accepted,'__ACCEPTED__'),
  (stage_materialization,'__MATERIALIZATION__'),(lock_acceptance_accounting,'__ACCOUNTING__'),
  (store_prepared_turn,'__PREPARED__')):
  assert hashlib.sha256(Path(inspect.getfile(function)).read_bytes()).hexdigest()==expected
 connector=PgConnector(config.pg); repo=JobRepository(connector)
 try:
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
  for mode in ('bare','materialization','prepared'):
   stage=mode+'_fixture'; job=uuid.uuid4(); jobs.append(job)
   thread=str(uuid.uuid4()); attempt=str(uuid.uuid4())
   def journal(revision,prompt):
    return {'schema_version':1,'attempt_id':attempt,'revision':revision,'receipts':[{
     'receipt_id':'fixture','provider':'gigachat','model':'GigaChat-2','kind':None,
     'prompt':prompt,'completion':2,'estimated':revision==1}]}
   def accepted(prompt):
    usage={'prompt_tokens':prompt,'completion_tokens':2,'total_tokens':prompt+2,
     'per_call_usage':[{'provider':'gigachat','model':'GigaChat-2','prompt':prompt,'completion':2}]}
    return accepted_turn(job_id=str(job),owner_id=str(owner),thread_id=thread,
     reply='Synthetic fixture',model='GigaChat-2',usage=usage)
   plan=MaterializationPlan.from_payload({'version':1,'reservation_id':None,'reserved_estimate':0,
    'workspace_id':None,'expires_at':None,'publications':[],
    'pricing':{'is_complex':False,'tools':[]},'elapsed_seconds':0,
    'library_files':[],'unresolved_assets':0})
   async def admit(db,value):
    if mode=='bare': return await stage_accepted(repo,db,value)
    if mode=='prepared': return await store_prepared_turn(repo,db,value)
    return await stage_materialization(repo,db,value,plan)
   async with connector.get_session_context() as db:
    db.add(UserLaunch(id=job,user_id=owner,type=ServiceType.CHAT,status=ProcessingStatus.PROCESSING,
     payload={'thread_id':thread,'fixture_marker':nonce,'_execution_attempt_v1':attempt,
      '_usage_journal_v1':journal(1,20)}))
    await db.commit()
   stage=mode+'_prior_checkpoint'
   async with connector.get_session_context() as db:
    assert await stage_usage_journal(repo,db,job_id=job,owner_id=owner,
     thread_id=thread,payload=journal(2,21))
    await db.commit()
   if mode=='prepared':
    stage='prepared_corrupt_accepted'
    async with connector.get_session_context() as db:
     corrupt=accepted(21).payload(); corrupt['sha256']='0'*64
     await db.execute(text("UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
      "'{_accepted_turn_v1}',CAST(:envelope AS JSONB)) WHERE id=:job AND user_id=:owner"),
      {'envelope':json.dumps(corrupt),'job':job,'owner':owner})
     try: await admit(db,accepted(21))
     except PreparedCheckpointInvalid: pass
     else: raise AssertionError('corrupt_accepted_admitted')
     await db.rollback()
   stage=mode+'_stale_refusal'
   async with connector.get_session_context() as db:
    try: await admit(db,accepted(20))
    except PreparedCheckpointInvalid: pass
    else: raise AssertionError('stale_usage_admitted')
    await db.rollback()
    saved=await db.scalar(select(UserLaunch.payload).where(UserLaunch.id==job))
    assert '_accepted_turn_v1' not in saved and '_prepared_turn_v1' not in saved
    assert saved['_usage_journal_v1']==journal(2,21)
    await db.rollback()
   async def late_checkpoint():
    async with connector.get_session_context() as late:
     incoming=journal(3,21)
     incoming['receipts'].append({**incoming['receipts'][0],
      'receipt_id':'late-call','prompt':1,'completion':1})
     try:
      await stage_usage_journal(repo,late,job_id=job,owner_id=owner,
       thread_id=thread,payload=incoming)
     except JobStateUnavailable:
      await late.rollback(); return 'rejected'
     else:
      await late.rollback(); return 'unexpected'
   stage=mode+'_row_lock'
   async with connector.get_session_context() as db:
    assert await admit(db,accepted(21))
    holder=await db.scalar(text('SELECT pg_backend_pid()'))
    pending=asyncio.create_task(late_checkpoint())
    try:
     async with connector.get_session_context() as observer:
      blocked=False
      for _ in range(100):
       blocked=bool(await observer.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
        "WHERE :holder=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock')"),{'holder':holder}))
       if blocked: break
       await asyncio.sleep(.02)
      assert blocked and not pending.done()
     await db.commit()
     assert await asyncio.wait_for(pending,5)=='rejected'
    finally:
     if not pending.done(): pending.cancel()
     await asyncio.gather(pending,return_exceptions=True)
   async with connector.get_session_context() as db:
    saved=await db.scalar(select(UserLaunch.payload).where(UserLaunch.id==job))
    assert saved['_usage_journal_v1']==journal(2,21)
    key='_prepared_turn_v1' if mode=='prepared' else '_accepted_turn_v1'
    assert saved[key]['body']['usage']['total_tokens']==23
    await db.rollback()
  stage='cleanup'
 finally:
  if pending is not None and not pending.done():
   pending.cancel(); await asyncio.gather(pending,return_exceptions=True)
  if owner is not None:
   async with connector.get_session_context() as db:
    for job in jobs:
     await db.execute(text('DELETE FROM profile.user_launch WHERE id=:job AND user_id=:owner '
      "AND payload->>'fixture_marker'=:marker"),{'job':job,'owner':owner,'marker':nonce})
    await db.commit()
    assert not list((await db.scalars(select(UserLaunch.id).where(UserLaunch.id.in_(jobs)))).all())
  await connector.close()
 print(json.dumps({'status':'passed','modes':3,'persisted_jobs':0}))
try:
 asyncio.run(asyncio.wait_for(main(),35))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_ordering_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(os.getenv("S37_LIVE_ACCEPTANCE_LOCK") != "1", reason="opt-in isolated dev SQL")
def test_actual_postgresql_acceptance_and_usage_ordering():
    base = Path("service/services/chat/infrastructure/chat_worker")
    probe = _PROBE
    for marker, filename in (
        ("__ACCEPTED__", "accepted_result.py"),
        ("__MATERIALIZATION__", "materialization_recovery.py"),
        ("__ACCOUNTING__", "acceptance_accounting.py"),
        ("__PREPARED__", "prepared_checkpoint.py"),
    ):
        probe = probe.replace(marker, hashlib.sha256((base / filename).read_bytes()).hexdigest())
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "acceptance_lock_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "acceptance_lock_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["modes"] == 3 and report["persisted_jobs"] == 0
