"""Charge settlement must not mutate another owner's reservation."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_billing_first_charge_race_live import _MODULES as _BILLING_MODULES

_MODULES = (
    *_BILLING_MODULES,
    "service/services/billing/persistence/reservation_maintenance.py",
    "service/services/billing/application/billing_service.py",
    "service/services/chat/infrastructure/chat_worker/billing/charging.py",
    "service/services/chat/infrastructure/chat_worker/billing/quote.py",
    "service/services/chat/infrastructure/chat_worker/execution/failure.py",
    "service/services/chat/infrastructure/chat_worker/billing/reservation/cleanup.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.billing.persistence import billing_repository,sql
from service.services.billing.persistence import reservation_maintenance
from service.services.billing.application import billing_service
from service.services.chat.infrastructure.chat_worker.billing import charging,quote
from service.services.chat.infrastructure.chat_worker.execution import failure
from service.services.chat.infrastructure.chat_worker.billing.reservation import (
 cleanup as reservation_cleanup,
)
from service.shared.repositories.decorators import session_processor
wire=json.load(sys.stdin);stage='source_parity'
async def main():
 global stage
 modules=(billing_repository,sql,session_processor,reservation_maintenance,billing_service,
  charging,quote,failure,reservation_cleanup)
 for module,digest in zip(modules,wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 cfg=Config();assert cfg.pg.host=='postgres'
 db=PgConnector(cfg.pg,force_new=True);repo=billing_repository.BillingRepository(db)
 owners=[];nonce=uuid.uuid4().hex;keys=[]
 try:
  stage='fixture'
  for _ in range(2):
   owner=uuid.uuid4();email='s37-reservation-'+owner.hex+'@fixture.invalid'
   owners.append((owner,email))
   async with db.get_session_context() as s:
    start,end=(await s.execute(text("SELECT date_trunc('month',CURRENT_DATE)::date,"
     "(date_trunc('month',CURRENT_DATE)+interval '1 month')::date"))).one()
    await s.execute(text('''INSERT INTO profile."user"
     (id,email,password_hash,available_launches,is_active,is_admin,topup_credit_balance)
     VALUES (:owner,:email,'!',0,false,false,0)'''),{'owner':owner,'email':email})
    await s.commit()
  actor=owners[0][0];foreign=owners[1][0]
  async def status(rid):
   async with db.get_session_context() as s:
    return await s.scalar(text('''SELECT status FROM profile.token_reservations
     WHERE reservation_id=CAST(:rid AS uuid)'''),{'rid':rid})
  modes=(('expired',actor),('released',actor),('missing',actor)) if wire.get('hold_states') else (
   ('owned',actor),('foreign',foreign))
  if wire.get('disconnect_count'):modes=(('owned',actor),)
  for mode,reservation_owner in modes:
   rid1=await repo.reserve(user_id=str(reservation_owner),credits=7,ttl_seconds=120,
    free_plan_credits=100,period_start=start,period_end=end)
   rid2=await repo.reserve(user_id=str(reservation_owner),credits=7,ttl_seconds=120,
    free_plan_credits=100,period_start=start,period_end=end)
   assert rid1 and rid2
   cleanup_rid=await repo.reserve(user_id=str(reservation_owner),credits=7,ttl_seconds=120,
    free_plan_credits=100,period_start=start,period_end=end)
   assert cleanup_rid
   stage='cleanup'
   for cleanup_index in range(2):
    if wire.get('disconnect_count') and cleanup_index==0:
     task=None
     async with db.get_session_context() as holder:
      pid=await holder.scalar(text('SELECT pg_backend_pid()'))
      await holder.execute(text('''SELECT reservation_id FROM profile.token_reservations
       WHERE reservation_id=CAST(:rid AS uuid) AND user_id=:owner FOR UPDATE'''),
       {'rid':cleanup_rid,'owner':actor})
      task=asyncio.create_task(charging._release_reservation(pg_connector=db,config=cfg,
       user_id=str(actor),reservation_id=cleanup_rid))
      try:
       limit=asyncio.get_running_loop().time()+3
       blocked=0
       while not blocked and asyncio.get_running_loop().time()<limit:
        async with db.get_session_context() as observer:
         blocked=await observer.scalar(text('''SELECT count(*) FROM pg_stat_activity
          WHERE :pid=ANY(pg_blocking_pids(pid))'''),{'pid':pid})
        if not blocked:await asyncio.sleep(0.01)
       assert blocked==1
       for _ in range(wire['disconnect_count']):
        task.cancel();await asyncio.sleep(0)
       assert not task.done()
      finally:
       await holder.rollback()
       if task is not None:
        try:await asyncio.wait_for(task,timeout=3)
        except asyncio.CancelledError:pass
    else:
     await charging._release_reservation(pg_connector=db,config=cfg,user_id=str(actor),
      reservation_id=cleanup_rid)
    assert await status(cleanup_rid)==('reserved' if mode=='foreign' else 'refunded')
   if mode=='expired':
    async with db.get_session_context() as s:
     await s.execute(text('''UPDATE profile.token_reservations
      SET expires_at=now()-interval '1 second'
      WHERE reservation_id=CAST(:rid AS uuid) AND user_id=:owner'''),
      {'rid':rid1,'owner':actor});await s.commit()
   elif mode=='released':await repo.release_reservation(user_id=str(actor),reservation_id=rid1)
   elif mode=='missing':
    await repo.release_reservation(user_id=str(actor),reservation_id=rid1)
    rid1=str(uuid.uuid4())
   primary_state={'foreign':'reserved','expired':'expired','released':'refunded',
    'missing':None}.get(mode,'committed')
   key='s37-reservation-'+nonce+'-'+mode;keys.append(key)
   async def charge(rid):
    return await repo.charge(user_id=str(actor),credits=7,tokens=42,raw_cost_rub=0,
     free_plan_credits=100,period_start=start,period_end=end,reservation_id=rid,
     idempotency_key=key,metadata={'acceptance_fixture':nonce})
   stage=mode+'_primary'
   outcome=await charge(rid1)
   assert outcome=={'from_subscription':7,'from_topup':0}
   stage=mode+'_primary_state'
   assert await status(rid1)==primary_state
   await repo.release_reservation(user_id=str(actor),reservation_id=rid1)
   assert await status(rid1)==primary_state
   stage=mode+'_duplicate'
   assert await charge(rid2)=={'from_subscription':0,'from_topup':0,'idempotent':True}
   assert await status(rid2)==('reserved' if mode=='foreign' else 'refunded')
   assert await charge(rid1)=={'from_subscription':0,'from_topup':0,'idempotent':True}
   assert await status(rid1)==primary_state
  stage='financial_integrity'
  async with db.get_session_context() as s:
   assert await s.scalar(text('SELECT count(*) FROM profile.billing_events WHERE user_id=:actor'),
    {'actor':actor})==len(modes)
   daily=(await s.execute(text('SELECT requests,tokens,credits FROM profile.usage_daily '
    'WHERE user_id=:actor'),{'actor':actor})).one()
   assert tuple(daily)==(len(modes),42*len(modes),7*len(modes))
   assert await s.scalar(text('SELECT used FROM profile.token_quotas WHERE user_id=:foreign'),
    {'foreign':foreign})==(None if wire.get('hold_states') or wire.get('disconnect_count') else 0)
   assert await s.scalar(text('SELECT count(*) FROM profile.billing_events WHERE user_id=:foreign'),
    {'foreign':foreign})==0
 finally:
  try:
   for owner,email in owners:
    async with db.get_session_context() as s:
     stored=await s.scalar(text('SELECT email FROM profile."user" WHERE id=:owner'),
      {'owner':owner})
     if stored is not None:
      assert stored==email
      await s.execute(text('''DELETE FROM profile.billing_events WHERE user_id=:owner
       AND metadata->>'acceptance_fixture'=:nonce'''),{'owner':owner,'nonce':nonce})
      await s.execute(text('DELETE FROM profile.usage_daily WHERE user_id=:owner'),{'owner':owner})
      await s.execute(text('DELETE FROM profile."user" WHERE id=:owner AND email=:email'),
       {'owner':owner,'email':email});await s.commit()
     for table,field in (('user','id'),('token_quotas','user_id'),
      ('token_reservations','user_id'),('usage_daily','user_id')):
      statement='SELECT count(*) FROM profile."'+table+'" WHERE '+field+'=:owner'
      assert await s.scalar(text(statement),{'owner':owner})==0
   async with db.get_session_context() as s:
    assert await s.scalar(text('''SELECT count(*) FROM profile.billing_events
     WHERE metadata->>'acceptance_fixture'=:nonce'''),{'nonce':nonce})==0
  finally:await db.close()
 return {'status':'passed','cases':len(modes),'hold_states':bool(wire.get('hold_states')),
  'disconnect_count':wire.get('disconnect_count',0),
  'reservation_states_verified':True,'single_charge_per_job':True,
  'fixtures_cleaned':True,'model_calls':0}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_reservation_owner_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_RESERVATION_OWNER") != "1", reason="inactive disposable SQL owner fixtures"
)
def test_owned_and_foreign_reservations_during_primary_and_duplicate_charge():
    _run_probe(hold_states=False)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_RESERVATION_OWNER") != "1", reason="inactive disposable SQL hold fixtures"
)
def test_expired_released_and_missing_holds_do_not_erase_incurred_charge():
    _run_probe(hold_states=True)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_RESERVATION_OWNER") != "1", reason="owned disposable SQL lock fixture"
)
@pytest.mark.parametrize("disconnect_count", [1, 3])
def test_disconnect_during_owned_cleanup_drains_blocked_sql_once(disconnect_count):
    _run_probe(hold_states=False, disconnect_count=disconnect_count)


def _run_probe(*, hold_states, disconnect_count=0):
    wire = {
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
        "hold_states": hold_states,
        "disconnect_count": disconnect_count,
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps(wire).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("reservation_owner_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {
            "source_parity",
            "fixture",
            "cleanup",
            "owned_primary",
            "owned_duplicate",
            "foreign_primary",
            "foreign_duplicate",
            "expired_primary",
            "expired_primary_state",
            "expired_duplicate",
            "released_primary",
            "released_primary_state",
            "released_duplicate",
            "missing_primary",
            "missing_primary_state",
            "owned_primary_state",
            "foreign_primary_state",
            "missing_duplicate",
            "financial_integrity",
        }:
            stage = "unknown"
        pytest.fail("reservation_owner_probe_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 1 if disconnect_count else 3 if hold_states else 2,
        "hold_states": hold_states,
        "disconnect_count": disconnect_count,
        "reservation_states_verified": True,
        "single_charge_per_job": True,
        "fixtures_cleaned": True,
        "model_calls": 0,
    }
