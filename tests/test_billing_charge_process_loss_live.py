"""Opt-in real SQL rollback/lost-ACK checks with disposable, inactive owner fixtures."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_billing_first_charge_race_live import _MODULES

_CHILD = r"""
import asyncio,hashlib,json,logging,sys
from datetime import date
from pathlib import Path
logging.disable(logging.CRITICAL)
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.billing.persistence import billing_repository,sql
from service.shared.repositories.decorators import session_processor
wire=json.loads(sys.stdin.readline())
for field in ('period_start','period_end'):
 wire['charge'][field]=date.fromisoformat(wire['charge'][field])
async def main():
 for module,digest in zip((billing_repository,sql,session_processor),wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 cfg=Config();assert cfg.pg.host=='postgres'
 db=PgConnector(cfg.pg,force_new=True);repo=billing_repository.BillingRepository(db)
 try:
  if wire['phase']=='before_commit':
   async with db.get_session_context() as s:
    outcome=await repo.charge(**wire['charge'],session=s)
    assert outcome=={'from_subscription':7,'from_topup':0}
    print(json.dumps({'status':'staged'}),flush=True)
    await asyncio.Future()
  else:
   outcome=await repo.charge(**wire['charge'])
   assert outcome=={'from_subscription':7,'from_topup':0}
   print(json.dumps({'status':'committed'}),flush=True)
   await asyncio.Future()
 finally:await db.close()
try:asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed'}),flush=True);raise SystemExit(1)
"""

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from datetime import date
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
 db=PgConnector(cfg.pg,force_new=True);repo=billing_repository.BillingRepository(db)
 fixtures=[];child=None;nonce=uuid.uuid4().hex
 try:
  for phase in ('before_commit','after_commit'):
   stage='fixture'
   owner=uuid.uuid4();email='s37-charge-loss-'+owner.hex+'@fixture.invalid'
   fixtures.append((owner,email))
   async with db.get_session_context() as s:
    start,end=(await s.execute(text("SELECT date_trunc('month',CURRENT_DATE)::date,"
     "(date_trunc('month',CURRENT_DATE)+interval '1 month')::date"))).one()
    await s.execute(text('''INSERT INTO profile."user"
     (id,email,password_hash,available_launches,is_active,is_admin,topup_credit_balance)
     VALUES (:owner,:email,'!',0,false,false,0)'''),{'owner':owner,'email':email})
    await s.commit()
   rid=await repo.reserve(user_id=str(owner),credits=7,ttl_seconds=300,
    free_plan_credits=100,period_start=start,period_end=end)
   assert rid
   key='s37-charge-loss-'+nonce+'-'+phase
   charge=dict(user_id=str(owner),credits=7,tokens=42,raw_cost_rub=0,
    free_plan_credits=100,period_start=start.isoformat(),period_end=end.isoformat(),
    reservation_id=rid,idempotency_key=key,metadata={'acceptance_fixture':nonce})
   stage='child_start'
   child=await asyncio.create_subprocess_exec(sys.executable,'-c',wire['child_source'],
    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.DEVNULL)
   child.stdin.write(json.dumps({'digests':wire['digests'],'phase':phase,'charge':charge}).encode()
    +b'\n');await child.stdin.drain();child.stdin.close();await child.stdin.wait_closed()
   stage='child_acceptance'
   ack=json.loads(await asyncio.wait_for(child.stdout.readline(),timeout=15))
   assert ack=={'status':'staged' if phase=='before_commit' else 'committed'}
   assert child.returncode is None
   stage='process_loss'
   child.kill();await asyncio.wait_for(child.wait(),timeout=5)
   assert child.returncode is not None and child.returncode<0
   child=None
   async def snapshot():
    async with db.get_session_context() as s:
     await s.execute(text("SET LOCAL statement_timeout='5s'"))
     events=await s.scalar(text('''SELECT count(*) FROM profile.billing_events
      WHERE user_id=:owner AND metadata->>'idempotency_key'=:key'''),
      {'owner':owner,'key':key})
     used=await s.scalar(text('SELECT used FROM profile.token_quotas WHERE user_id=:owner'),
      {'owner':owner})
     status=await s.scalar(text('''SELECT status FROM profile.token_reservations
      WHERE reservation_id=CAST(:rid AS uuid) AND user_id=:owner'''),{'rid':rid,'owner':owner})
     daily=(await s.execute(text('SELECT requests,tokens,credits FROM profile.usage_daily '
      'WHERE user_id=:owner'),{'owner':owner})).first()
     return events,used,status,tuple(daily) if daily else None
   stage='post_loss_state'
   assert await snapshot()==((0,0,'reserved',None) if phase=='before_commit' else
    (1,7,'committed',(1,42,7)))
   for field in ('period_start','period_end'):charge[field]=date.fromisoformat(charge[field])
   stage='resume'
   outcome=await repo.charge(**charge)
   assert outcome==({'from_subscription':7,'from_topup':0} if phase=='before_commit' else
    {'from_subscription':0,'from_topup':0,'idempotent':True})
   stage='replay'
   assert await repo.charge(**charge)=={
    'from_subscription':0,'from_topup':0,'idempotent':True}
   assert await snapshot()==(1,7,'committed',(1,42,7))
 finally:
  try:
   if child is not None and child.returncode is None:
    child.kill();await asyncio.wait_for(child.wait(),timeout=5)
   for owner,email in fixtures:
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
      assert await s.scalar(text('SELECT count(*) FROM profile."'+table+'" WHERE '+field+
       '=:owner'),{'owner':owner})==0
   async with db.get_session_context() as s:
    assert await s.scalar(text('''SELECT count(*) FROM profile.billing_events
     WHERE metadata->>'acceptance_fixture'=:nonce'''),{'nonce':nonce})==0
  finally:await db.close()
 return {'status':'passed','cases':2,'rollback_verified':True,'lost_ack_reused':True,
  'single_charge_per_job':True,'fixtures_cleaned':True,'model_calls':0}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_charge_process_loss_probes_compile_without_side_effects():
    ast.parse(_CHILD)
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_CHARGE_PROCESS_LOSS") != "1", reason="inactive owned SQL process fixtures"
)
def test_charge_recovers_from_process_loss_before_and_after_commit():
    wire = {
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
        "child_source": _CHILD,
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps(wire).encode(),
        capture_output=True,
        timeout=75,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("charge_process_loss_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {
            "source_parity",
            "fixture",
            "child_start",
            "child_acceptance",
            "process_loss",
            "post_loss_state",
            "resume",
            "replay",
        }:
            stage = "unknown"
        pytest.fail("charge_process_loss_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 2,
        "rollback_verified": True,
        "lost_ack_reused": True,
        "single_charge_per_job": True,
        "fixtures_cleaned": True,
        "model_calls": 0,
    }
