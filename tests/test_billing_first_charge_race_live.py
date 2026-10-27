"""Actual first-charge contention on inactive disposable SQL fixtures only."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/services/billing/persistence/billing_repository.py",
    "service/services/billing/persistence/sql.py",
    "service/shared/repositories/decorators/session_processor.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.billing.persistence import billing_repository,sql
from service.shared.repositories.decorators import session_processor
wire=json.load(sys.stdin);stage='source_parity'
async def main():
 global stage
 for module,digest in zip((billing_repository,sql,session_processor),wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 cfg=Config();assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True);repo=billing_repository.BillingRepository(connector)
 fixtures=[];pending=None
 try:
  for warm in (False,True):
   stage='fixture';owner=uuid.uuid4();key='s37-first-charge-'+owner.hex
   email='s37-first-charge-'+owner.hex+'@fixture.invalid';fixtures.append((owner,email,key))
   async with connector.get_session_context() as db:
    start,end=(await db.execute(text("SELECT date_trunc('month',CURRENT_DATE)::date,"
     "(date_trunc('month',CURRENT_DATE)+interval '1 month')::date"))).one()
    await db.execute(text('''INSERT INTO profile."user"
     (id,email,password_hash,available_launches,is_active,is_admin,topup_credit_balance)
     VALUES (:owner,:email,'!',0,false,false,0)'''),{'owner':owner,'email':email})
    if warm:
     await db.execute(text(sql._PROVISION_QUOTA_SQL),{'user_id':str(owner),
      'period_start':start,'period_end':end,'limit':100})
    await db.commit()
   async def charge(db):
    return await repo.charge(user_id=str(owner),credits=7,tokens=42,raw_cost_rub=0,
     free_plan_credits=100,period_start=start,period_end=end,idempotency_key=key,
     metadata={'acceptance_fixture':key},session=db)
   stage='cold_contention' if not warm else 'warm_contention'
   ready=asyncio.Event();second_pid=None
   async def contender():
    nonlocal second_pid
    async with connector.get_session_context() as db:
     await db.execute(text("SET LOCAL statement_timeout='8000ms'"))
     second_pid=await db.scalar(text('SELECT pg_backend_pid()'));ready.set()
     result=await charge(db);await db.commit();return result
   async with connector.get_session_context() as first_db:
    first_pid=await first_db.scalar(text('SELECT pg_backend_pid()'))
    first=await charge(first_db)
    assert first=={'from_subscription':7,'from_topup':0}
    pending=asyncio.create_task(contender());await asyncio.wait_for(ready.wait(),3)
    deadline=asyncio.get_running_loop().time()+3
    while True:
     async with connector.get_session_context() as observer:
      blockers=await observer.scalar(text('SELECT pg_blocking_pids(:pid)'),{'pid':second_pid})
     if first_pid in blockers:break
     assert not pending.done() and asyncio.get_running_loop().time()<deadline
     await asyncio.sleep(.01)
    await first_db.commit()
   second=await asyncio.wait_for(pending,5);pending=None
   assert second=={'from_subscription':0,'from_topup':0,'idempotent':True}
   stage='single_settlement'
   async with connector.get_session_context() as db:
    events=(await db.execute(text('''SELECT tokens,metadata FROM profile.billing_events
     WHERE user_id=:owner AND event_type='usage' '''),{'owner':owner})).all()
    assert len(events)==1 and events[0][0]==42
    assert events[0][1]['idempotency_key']==key and events[0][1]['credits']==7
    daily=(await db.execute(text('''SELECT requests,tokens,credits,raw_cost_rub
     FROM profile.usage_daily WHERE user_id=:owner'''),{'owner':owner})).one()
    assert tuple(daily)==(1,42,7,0)
    assert await db.scalar(text('SELECT used FROM profile.token_quotas WHERE user_id=:owner'),
     {'owner':owner})==7
    assert await db.scalar(text('SELECT topup_credit_balance FROM profile."user" WHERE id=:owner'),
     {'owner':owner})==0
 finally:
  if pending is not None:
   pending.cancel();await asyncio.gather(pending,return_exceptions=True)
  try:
   for owner,email,key in fixtures:
    async with connector.get_session_context() as db:
     stored=await db.scalar(text('SELECT email FROM profile."user" WHERE id=:owner'),
      {'owner':owner})
     if stored is not None:
      assert stored==email
      # billing_events is SET NULL on user deletion: remove exact fixture facts first.
      await db.execute(text('''DELETE FROM profile.billing_events WHERE user_id=:owner
       AND metadata->>'idempotency_key'=:key'''),{'owner':owner,'key':key})
      await db.execute(text('DELETE FROM profile.usage_daily WHERE user_id=:owner'),{'owner':owner})
      await db.execute(text('DELETE FROM profile."user" WHERE id=:owner AND email=:email'),
       {'owner':owner,'email':email});await db.commit()
     for table,field in (('user','id'),('token_quotas','user_id'),('usage_daily','user_id')):
      statement='SELECT count(*) FROM profile."'+table+'" WHERE '+field+'=:owner'
      assert await db.scalar(text(statement),{'owner':owner})==0
     assert await db.scalar(text('''SELECT count(*) FROM profile.billing_events
      WHERE metadata->>'idempotency_key'=:key'''),{'key':key})==0
  finally:await connector.close()
 return {'status':'passed','quota_modes':2,'blocked_contenders':2,
  'single_charge_per_job':True,'daily_aggregate_exact':True,'fixtures_cleaned':True,'model_calls':0}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_first_charge_probe_compiles_and_checks_real_blocking():
    ast.parse(_PROBE)
    assert "pg_blocking_pids" in _PROBE
    assert "is_active,is_admin,topup_credit_balance" in _PROBE
    assert "'!',0,false,false,0" in _PROBE
    assert "free_plan_credits=100" in _PROBE
    assert "await first_db.commit()" in _PROBE


@pytest.mark.skipif(
    os.getenv("S37_LIVE_FIRST_CHARGE_RACE") != "1",
    reason="inactive disposable SQL fixture with real PostgreSQL contention",
)
def test_first_charge_is_single_under_cold_and_warm_quota_contention():
    wire = {"digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES]}
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
        pytest.fail("first_charge_probe_protocol_unavailable")
    assert result.returncode == 0, "first_charge_probe_failed"
    assert report == {
        "status": "passed",
        "quota_modes": 2,
        "blocked_contenders": 2,
        "single_charge_per_job": True,
        "daily_aggregate_exact": True,
        "fixtures_cleaned": True,
        "model_calls": 0,
    }
