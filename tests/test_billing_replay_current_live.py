"""Replay only an existing GigaChat charge; never issue a new model call."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/services/chat/infrastructure/chat_worker/billing/charging.py",
    "service/services/chat/infrastructure/chat_worker/billing/quote.py",
    "service/services/billing/application/billing_service.py",
    "service/services/billing/application/pricing_service.py",
    "service/services/billing/persistence/billing_repository.py",
    "service/services/billing/persistence/sql.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.infrastructure.chat_worker.billing import charging,quote
from service.services.billing.application import billing_service,pricing_service
from service.services.billing.persistence import billing_repository,sql
wire=json.load(sys.stdin);stage='source_parity'
async def main():
 global stage
 for module,digest in zip((charging,quote,billing_service,pricing_service,billing_repository,sql),
  wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 cfg=Config();assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 try:
  stage='owned_existing_charge'
  async with connector.get_session_context() as db:
   rows=(await db.execute(text('''SELECT e.user_id,e.tokens,e.metadata
    FROM profile.billing_events e JOIN profile."user" u ON u.id=e.user_id
    WHERE u.email=:email AND e.event_type='usage'
     AND e.metadata->>'idempotency_key' IS NOT NULL
    ORDER BY e.created_at DESC LIMIT 1'''),
    {'email':'s38-video-acceptance@example.com'})).mappings().all()
   assert len(rows)==1
   row=rows[0];meta=row['metadata'];owner=str(row['user_id'])
   key=meta['idempotency_key'];calls=meta.get('per_call')
   assert isinstance(key,str) and key and row['tokens']>0
   assert isinstance(calls,list) and calls
   assert all(isinstance(c,dict) and c.get('provider')=='gigachat' for c in calls)
   assert meta['prompt']+meta['completion']==row['tokens']
  repository=billing_repository.BillingRepository(connector)
  async def snapshot():
   balance=await repository.get_balance(user_id=owner);assert balance is not None
   async with connector.get_session_context() as db:
    events=(await db.execute(text('''SELECT id,tokens,metadata FROM profile.billing_events
     WHERE user_id=CAST(:owner AS uuid) AND event_type='usage'
     ORDER BY id'''),{'owner':owner})).all()
    daily=(await db.execute(text('''SELECT day,requests,tokens,credits,raw_cost_rub
     FROM profile.usage_daily WHERE user_id=CAST(:owner AS uuid) ORDER BY day'''),
     {'owner':owner})).all()
   return balance,events,daily
  before=await snapshot()
  async def replay():
   return await charging._charge_usage(
    pg_connector=connector,redis_client=None,user_id=owner,
    execution_result={'prompt_tokens':meta['prompt'],
     'completion_tokens':meta['completion'],'total_tokens':row['tokens'],
     'per_call_usage':calls,'reply_chars_count':1,'used_tools':meta.get('tools') or []},
    thread_id=meta.get('thread_id'),job_id=key,resolved_model=meta.get('model'),
    selected_model=meta.get('model'),config=cfg,require_persisted=True)
  stage='sequential_replay';assert await replay()==0
  stage='concurrent_replay';assert await asyncio.gather(replay(),replay())==[0,0]
  stage='financial_integrity';assert await snapshot()==before
  async with connector.get_session_context() as db:
   count=await db.scalar(text('''SELECT count(*) FROM profile.billing_events
    WHERE user_id=CAST(:owner AS uuid) AND event_type='usage'
     AND metadata->>'idempotency_key'=:key'''),{'owner':owner,'key':key})
   assert count==1
  return {'status':'passed','replays':3,'existing_usage_events':1,
   'balance_unchanged':True,'all_usage_events_unchanged':True,
   'daily_aggregate_unchanged':True,'model_calls':0}
 finally:
  await connector.close()
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_replay_probe_compiles_and_only_reuses_existing_key():
    ast.parse(_PROBE)
    assert "job_id=key" in _PROBE
    assert "await asyncio.gather(replay(),replay())" in _PROBE
    assert "'idempotency_key' IS NOT NULL" in _PROBE
    assert "c.get('provider')=='gigachat'" in _PROBE


@pytest.mark.skipif(
    os.getenv("S37_LIVE_CURRENT_BILLING_REPLAY") != "1",
    reason="existing owned dev GigaChat charge replay",
)
def test_existing_gigachat_charge_sequential_and_concurrent_replay():
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
        pytest.fail("billing_replay_protocol_unavailable")
    assert result.returncode == 0, "billing_replay_failed"
    assert report == {
        "status": "passed",
        "replays": 3,
        "existing_usage_events": 1,
        "balance_unchanged": True,
        "all_usage_events_unchanged": True,
        "daily_aggregate_unchanged": True,
        "model_calls": 0,
    }
