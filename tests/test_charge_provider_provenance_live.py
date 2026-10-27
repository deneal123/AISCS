"""Current worker/SQL provenance with scripted price and inactive disposable owners."""

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
    "service/services/chat/infrastructure/chat_worker/billing/usage/provenance.py",
    "service/services/billing/application/billing_service.py",
    "service/services/billing/persistence/billing_repository.py",
    "service/services/billing/persistence/sql.py",
    "service/services/analytics/application/memory/service.py",
    "service/services/analytics/application/memory/usage.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.infrastructure.chat_worker.billing import charging,quote
from service.services.chat.infrastructure.chat_worker.billing.usage import (
 provenance as usage_provenance,
)
from service.services.billing.application import billing_service,pricing_service
from service.services.billing.persistence import billing_repository,sql
from service.services.analytics.application.memory import (
 service as memory_service, usage as memory_usage,
)
wire=json.load(sys.stdin);stage='source_parity'
async def main():
 global stage
 for module,digest in zip((charging,quote,usage_provenance,billing_service,billing_repository,sql,
  memory_service,memory_usage),
  wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 cfg=Config();assert cfg.pg.host=='postgres';db=PgConnector(cfg.pg,force_new=True)
 owner=uuid.uuid4();email='s37-provenance-'+owner.hex+'@fixture.invalid';nonce=uuid.uuid4().hex
 try:
  stage='fixture'
  async with db.get_session_context() as s:
   await s.execute(text('''INSERT INTO profile."user"
    (id,email,password_hash,available_launches,is_active,is_admin,topup_credit_balance)
    VALUES (:owner,:email,'!',0,false,false,0)'''),{'owner':owner,'email':email});await s.commit()
  cases=((('gigachat','GigaChat-2'),), (('routerai','openai/gpt-4o'),),
   (('gigachat','GigaChat-2'),('routerai','openai/gpt-4o')), ((None,'openai/gpt-4o'),))
  for index,case in enumerate(cases):
   calls=[{'model':model,'prompt':2,'completion':1,'total':3,'receipt_id':uuid.uuid4().hex,
    **({'provider':provider} if provider else {})} for provider,model in case]
   expected=case[0][0] if len(case)==1 else None
   async def price(_self,**kwargs):
    # The existing chosen-model ceiling also prices a model-substituted copy.
    priced=kwargs['per_call_usage'];assert len(priced)==len(calls)
    assert all((a.get('provider'),a['prompt'],a['completion'],a['receipt_id'])==
     (b.get('provider'),b['prompt'],b['completion'],b['receipt_id'])
     for a,b in zip(priced,calls,strict=True))
    return SimpleNamespace(credits=7,raw_cost_rub=0,model_breakdown=[])
   billing_job_id='s37-provenance-'+nonce+'-'+str(index)
   args=dict(pg_connector=db,redis_client=None,user_id=str(owner),config=cfg,
    execution_result={'total_tokens':3*len(calls),'prompt_tokens':2*len(calls),
     'completion_tokens':len(calls),'reply_chars_count':10,'per_call_usage':calls},
    thread_id='s37-provenance-'+nonce,job_id=billing_job_id,resolved_model=calls[-1]['model'])
   charge=charging._charge_usage
   if wire['mode']=='router':
    usage=args.pop('execution_result');args.pop('resolved_model')
    args['session_data']={'_router_usage':{'prompt':usage['prompt_tokens'],
     'completion':usage['completion_tokens'],'total':usage['total_tokens'],'calls':calls}}
    charge=charging._charge_router_usage;billing_job_id+=':router'
   elif wire['mode']=='memory':
    args.pop('execution_result');args.pop('resolved_model')
    projected={}
    memory_service.MemoryService._accumulate_usage(projected,{'calls':calls})
    args['mem_usage']=projected
    charge=charging._charge_memory_usage;billing_job_id+=':memory'
   stage='charge'
   with patch.object(pricing_service.PricingService,'price_request',price):
    assert await charge(**args)==7
    assert await charge(**args)==0
   stage='metadata'
   async with db.get_session_context() as s:
    rows=(await s.execute(text('''SELECT tokens,metadata FROM profile.billing_events
     WHERE user_id=:owner AND event_type='usage' AND metadata->>'idempotency_key'=:key'''),
     {'owner':owner,'key':billing_job_id})).all()
    assert len(rows)==1;tokens,meta=rows[0]
    assert tokens==3*len(calls) and meta['per_call']==calls
    assert meta.get('provider')==expected
    if expected is None:assert 'provider' not in meta
    assert meta['from_subscription']==7 and meta['from_topup']==0
  stage='accounting'
  async with db.get_session_context() as s:
   assert await s.scalar(text('SELECT used FROM profile.token_quotas WHERE user_id=:owner'),
    {'owner':owner})==28
   assert await s.scalar(text('SELECT count(*) FROM profile.billing_events WHERE user_id=:owner'),
    {'owner':owner})==4
   daily=(await s.execute(text('SELECT requests,tokens,credits FROM profile.usage_daily '
    'WHERE user_id=:owner'),{'owner':owner})).one()
   assert tuple(daily)==(4,15,28)
 finally:
  try:
   async with db.get_session_context() as s:
    stored=await s.scalar(text('SELECT email FROM profile."user" WHERE id=:owner'),{'owner':owner})
    if stored is not None:
     assert stored==email
     await s.execute(text('''DELETE FROM profile.billing_events WHERE user_id=:owner
      AND metadata->>'idempotency_key' LIKE :prefix'''),
      {'owner':owner,'prefix':'s37-provenance-'+nonce+'-%'})
     assert await s.scalar(text('SELECT count(*) FROM profile.billing_events WHERE user_id=:owner'),
      {'owner':owner})==0
     await s.execute(text('DELETE FROM profile.usage_daily WHERE user_id=:owner'),{'owner':owner})
     await s.execute(text('DELETE FROM profile."user" WHERE id=:owner AND email=:email'),
      {'owner':owner,'email':email});await s.commit()
    for table,field in (('user','id'),('token_quotas','user_id'),('usage_daily','user_id')):
     assert await s.scalar(text('SELECT count(*) FROM profile."'+table+'" WHERE '+field+
      '=:owner'),{'owner':owner})==0
    assert await s.scalar(text('''SELECT count(*) FROM profile.billing_events
     WHERE metadata->>'idempotency_key' LIKE :prefix'''),
     {'prefix':'s37-provenance-'+nonce+'-%'})==0
  finally:await db.close()
 return {'status':'passed','cases':4,'receipt_providers_preserved':True,
  'single_charge_per_job':True,'fixtures_cleaned':True,'model_calls':0}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_provider_provenance_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PROVIDER_PROVENANCE") != "1", reason="inactive disposable SQL provenance"
)
@pytest.mark.parametrize("mode", ["answer", "router", "memory"])
def test_real_charge_metadata_uses_receipts_and_replay_remains_zero(mode):
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps(
            {
                "digests": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in _MODULES],
                "mode": mode,
            }
        ).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("provider_provenance_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {"source_parity", "fixture", "charge", "metadata", "accounting"}:
            stage = "unknown"
        pytest.fail("provider_provenance_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 4,
        "receipt_providers_preserved": True,
        "single_charge_per_job": True,
        "fixtures_cleaned": True,
        "model_calls": 0,
    }
