"""Opt-in synthetic SQL rows; no providers, active holds, messages or charges."""

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
from sqlalchemy import text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.models.db.db_models import UserLaunch
from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus,ServiceType
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.jobs.persistence.transitions import guarded_payload
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
 stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.delivery import (
 usage_checkpoint_sink,
)
from service.services.chat.infrastructure.chat_worker.execution.attempt import commit_preflight
from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
 stage_execution_accounting,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
 MutableRunState,WorkerRunRequest,
)
from service.services.chat.infrastructure.chat_worker.billing.reservation.recovery import (
 verify_accounting,ReservationState,_OWNED_RESERVATION,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
stage='freshness'; owner=None; job=uuid.uuid4(); marker=str(uuid.uuid4()); thread=str(uuid.uuid4())
reservation=uuid.uuid4()
async def main():
 global stage,owner
 source=Path(inspect.getfile(JobRepository)).read_bytes()
 assert hashlib.sha256(source).hexdigest()=='__DIGEST__'
 transitions=Path(inspect.getfile(guarded_payload)).read_bytes()
 assert hashlib.sha256(transitions).hexdigest()=='__TRANSITIONS_DIGEST__'
 journal_source=Path(inspect.getfile(stage_usage_journal)).read_bytes()
 assert hashlib.sha256(journal_source).hexdigest()=='__JOURNAL_DIGEST__'
 delivery_source=Path(inspect.getfile(usage_checkpoint_sink)).read_bytes()
 assert hashlib.sha256(delivery_source).hexdigest()=='__DELIVERY_DIGEST__'
 preflight_source=Path(inspect.getfile(commit_preflight)).read_bytes()
 assert hashlib.sha256(preflight_source).hexdigest()=='__PREFLIGHT_DIGEST__'
 accounting_source=Path(inspect.getfile(stage_execution_accounting)).read_bytes()
 assert hashlib.sha256(accounting_source).hexdigest()=='__ACCOUNTING_DIGEST__'
 recovery_source=Path(inspect.getfile(verify_accounting)).read_bytes()
 assert hashlib.sha256(recovery_source).hexdigest()=='__RESERVATION_DIGEST__'
 connector=PgConnector(config.pg); repo=JobRepository(connector)
 try:
  stage='fixture'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   db.add(UserLaunch(id=job,user_id=owner,type=ServiceType.CHAT,
    status=ProcessingStatus.PROCESSING,payload={'thread_id':thread,'fixture_marker':marker}))
   await db.commit()
   await db.execute(text('INSERT INTO profile.token_reservations '
    '(reservation_id,user_id,tokens_reserved,expires_at,status,refunded_at) '
    "VALUES (:rid,:owner,70,now()-interval '1 day','refunded',now())"),
    {'rid':reservation,'owner':owner})
   await db.commit()
  stage='owner_thread'
  async with connector.get_session_context() as db:
   assert not await repo.claim_chat_execution(job,uuid.uuid4(),thread,str(uuid.uuid4()),session=db)
   assert not await repo.claim_chat_execution(
    job,owner,str(uuid.uuid4()),str(uuid.uuid4()),session=db)
   await db.rollback()
  stage='claim'
  async def claim(attempt):
   async with connector.get_session_context() as db:
    result=await repo.claim_chat_execution(job,owner,thread,attempt,session=db)
    await db.commit()
    return result
  attempts=[str(uuid.uuid4()),str(uuid.uuid4())]
  results=await asyncio.gather(*(claim(attempt) for attempt in attempts))
  assert sorted(results)==[False,True]
  accepted=attempts[results.index(True)]
  stage='sticky_update'
  async with connector.get_session_context() as db:
   row=await repo.fetch_job_by_id(job,owner,session=db)
   assert row.payload['_execution_attempt_v1']==accepted
   row.payload={**row.payload}; row.payload.pop('_execution_attempt_v1')
   await repo.update_job_status(row,session=db); await db.commit()
  stage='reconnect'
  await connector.close()
  connector=PgConnector(config.pg); repo=JobRepository(connector)
  async with connector.get_session_context() as db:
   row=await repo.fetch_job_by_id(job,owner,session=db)
   assert row.payload['_execution_attempt_v1']==accepted
   assert not await repo.claim_chat_execution(job,owner,thread,str(uuid.uuid4()),session=db)
   await db.rollback()
  stage='usage_journal'
  journal={'schema_version':1,'attempt_id':accepted,'revision':1,'receipts':[{
   'receipt_id':'synthetic-call','provider':'openai','model':'synthetic','kind':None,
   'prompt':20,'completion':2,'estimated':True}]}
  state=MutableRunState(execution_attempt_id=accepted,
   reservation_id=str(reservation),reserved_estimate=70)
  sink=usage_checkpoint_sink(repo,WorkerRunRequest(str(job),thread,'synthetic',str(owner)),state)
  stage='independent_ack_lock'
  async with connector.get_session_context() as db:
   holder=await db.scalar(text('SELECT pg_backend_pid()'))
   row=await repo.fetch_job_by_id(job,owner,session=db)
   await repo.update_job_status(row,session=db)
   request=WorkerRunRequest(str(job),thread,'synthetic',str(owner))
   await stage_execution_accounting(repo,db,request,state)
   pending=asyncio.create_task(sink(journal))
   try:
    blocked=False
    async with connector.get_session_context() as monitor:
     for _ in range(100):
      blocked=bool(await monitor.scalar(text(
       "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
       "WHERE :holder=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock')"
      ),{'holder':holder}))
      if blocked: break
      await asyncio.sleep(.02)
    assert blocked and not pending.done()
    await commit_preflight(db)
    await asyncio.wait_for(pending,3)
   finally:
    if not pending.done(): pending.cancel()
    await asyncio.gather(pending,return_exceptions=True)
  assert state.usage_checkpoint_observed and state.usage_checkpointed
  expected_accounting={'schema_version':1,'attempt_id':accepted,
   'reservation_id':str(reservation),'reserved_estimate':70}
  stage='owned_reservation_recovery'
  async with connector.get_session_context() as db:
   row=await repo.fetch_job_by_id(job,owner,session=db)
   stage='reservation_sql'
   record=(await db.execute(_OWNED_RESERVATION,{'reservation':reservation,
    'owner':owner,'job':str(job)})).mappings().first()
   stage='reservation_record'
   assert record is not None
   stage='reservation_integer'
   assert type(record['tokens_reserved']) is int
   stage='reservation_payload'
   assert row.payload.get('_execution_accounting_v1')==expected_accounting
   assert row.payload.get('_execution_attempt_v1')==accepted
   assert row.payload.get('thread_id')==thread
   stage='reservation_record_protocol'
   assert type(record['expired']) is bool and type(record['charged']) is bool
   stage='reservation_record_status'
   assert record['status']=='expired'
   stage='reservation_verification'
   verified=await verify_accounting(db,row.payload,request)
   stage='reservation_verified_state'
   assert verified.reservation_state==ReservationState.EXPIRED
   assert verified.facts.reserved_estimate==70
   foreign=WorkerRunRequest(str(job),thread,'synthetic',str(uuid.uuid4()))
   try:
    await verify_accounting(db,row.payload,foreign)
   except JobStateUnavailable:
    pass
   else:
    raise AssertionError
   await db.rollback()
  journal['revision']=2; journal['receipts'][0].update(prompt=19,completion=3,estimated=False)
  async with connector.get_session_context() as db:
   assert await stage_usage_journal(repo,db,job_id=job,owner_id=owner,
    thread_id=thread,payload=journal)
   await db.commit()
  async with connector.get_session_context() as db:
   assert not await stage_usage_journal(repo,db,job_id=job,owner_id=owner,
    thread_id=thread,payload=journal)
   row=await repo.fetch_job_by_id(job,owner,session=db)
   assert row.payload['_usage_journal_v1']==journal
   assert row.payload['_execution_accounting_v1']==expected_accounting
   row.payload={**row.payload}; row.payload.pop('_usage_journal_v1')
   row.payload.pop('_execution_accounting_v1')
   await repo.update_job_status(row,session=db); await db.commit()
  async with connector.get_session_context() as db:
   row=await repo.fetch_job_by_id(job,owner,session=db)
   assert row.payload['_usage_journal_v1']==journal
   assert row.payload['_execution_accounting_v1']==expected_accounting
   await db.rollback()
 finally:
  if owner is not None:
   async with connector.get_session_context() as db:
    await db.execute(text('DELETE FROM profile.token_reservations '
     'WHERE reservation_id=:rid AND user_id=:owner AND tokens_reserved=70 '
     "AND status IN ('refunded','expired')"),{'rid':reservation,'owner':owner})
    await db.execute(text('DELETE FROM profile.user_launch WHERE id=:id AND user_id=:owner '
     "AND payload->>'fixture_marker'=:marker"),{'id':job,'owner':owner,'marker':marker})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.user_launch WHERE id=:id'),
     {'id':job})==0
    assert await db.scalar(text('SELECT count(*) FROM profile.token_reservations '
     'WHERE reservation_id=:rid'),{'rid':reservation})==0
  await connector.close()
try:
 asyncio.run(main()); print(json.dumps({'status':'passed','single_claim':True,
  'sticky':True,'journal':True}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def _probe_sources():
    source = Path("service/services/jobs/persistence/job_repository.py")
    transitions = source.with_name("transitions.py")
    journal = Path("service/services/chat/infrastructure/chat_worker/billing/usage/journal.py")
    delivery = journal.with_name("delivery.py")
    worker = journal.parents[2]
    preflight = worker / "execution/attempt.py"
    accounting = worker / "billing/execution_accounting.py"
    reservation_recovery = worker / "billing/reservation/recovery.py"
    return source, transitions, journal, delivery, preflight, accounting, reservation_recovery


def test_execution_attempt_probe_compiles():
    ast.parse(_PROBE)
    assert all(path.is_file() for path in _probe_sources())


@pytest.mark.skipif(os.getenv("S37_LIVE_EXECUTION_ATTEMPT") != "1", reason="opt-in dev SQL")
def test_owned_execution_attempt_is_single_and_durable():
    source, transitions, journal, delivery, preflight, accounting, reservation_recovery = (
        _probe_sources()
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "docker/.env.dev",
            "-f",
            "docker/docker-compose.dev.yaml",
            "--profile",
            "dev",
            "--profile",
            "celery",
            "exec",
            "-T",
            "backend",
            "python",
            "-",
        ],
        input=_PROBE.replace("__DIGEST__", hashlib.sha256(source.read_bytes()).hexdigest())
        .replace("__TRANSITIONS_DIGEST__", hashlib.sha256(transitions.read_bytes()).hexdigest())
        .replace("__JOURNAL_DIGEST__", hashlib.sha256(journal.read_bytes()).hexdigest())
        .replace("__DELIVERY_DIGEST__", hashlib.sha256(delivery.read_bytes()).hexdigest())
        .replace("__PREFLIGHT_DIGEST__", hashlib.sha256(preflight.read_bytes()).hexdigest())
        .replace("__ACCOUNTING_DIGEST__", hashlib.sha256(accounting.read_bytes()).hexdigest())
        .replace(
            "__RESERVATION_DIGEST__", hashlib.sha256(reservation_recovery.read_bytes()).hexdigest()
        )
        .encode(),
        capture_output=True,
        cwd="..",
        timeout=30,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "execution_attempt_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "execution_attempt_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["single_claim"] and report["sticky"]
    assert report["journal"]
