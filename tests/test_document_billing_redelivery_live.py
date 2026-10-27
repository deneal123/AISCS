"""Opt-in replay of an already charged job, never a new model invocation."""

import asyncio
import json
import os
import subprocess

import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_BILLING_REDELIVERY") != "1", reason="existing dev charge replay"
)
async def test_replaying_existing_document_usage_preserves_event_and_balance():
    probe = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_usage
async def main():
 config=Config(); connector=PgConnector(config.pg)
 async with connector.get_session_context() as session:
  result=await session.execute(text('''SELECT e.user_id,e.tokens,e.metadata
   FROM profile.billing_events e JOIN profile."user" u ON u.id=e.user_id
   WHERE u.email=:email AND e.event_type='usage'
    AND e.metadata->>'idempotency_key'=(SELECT j.billing_job_id
     FROM profile.document_publication_job j WHERE j.user_id=e.user_id
     AND j.role='source_bundle' AND j.status='delivered'
     ORDER BY j.created_at DESC LIMIT 1)'''),
   {'email':'s37-e2e-391e5206659a3654@example.com'})
  rows=list(result.mappings()); assert len(rows)==1
  row=rows[0]; meta=row['metadata']; key=meta['idempotency_key']
  assert key and row['tokens']>0 and meta.get('per_call')
 repository=BillingRepository(connector)
 before=await repository.get_balance(user_id=str(row['user_id']))
 assert before is not None
 replay_results=[]
 for _ in range(2):
  replay_results.append(await _charge_usage(
   pg_connector=connector,redis_client=None,user_id=str(row['user_id']),
   execution_result={'prompt_tokens':meta['prompt'],'completion_tokens':meta['completion'],
    'total_tokens':row['tokens'],'per_call_usage':meta['per_call'],
    'reply_chars_count':1,'used_tools':meta.get('tools') or []},
   thread_id=meta['thread_id'],job_id=key,resolved_model=meta.get('model'),
   selected_model=meta.get('model'),config=config,require_persisted=True))
 after=await repository.get_balance(user_id=str(row['user_id']))
 async with connector.get_session_context() as session:
  count=await session.scalar(text('''SELECT count(*) FROM profile.billing_events
   WHERE user_id=:owner AND event_type='usage' AND metadata->>'idempotency_key'=:key'''),
   {'owner':row['user_id'],'key':key})
 print(json.dumps({'replayed_twice':replay_results==[0,0],
  'balance_unchanged':before==after,'usage_events':count}))
asyncio.run(main())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail("billing_redelivery_probe_failed")
    assert json.loads(result.stdout) == {
        "replayed_twice": True,
        "balance_unchanged": True,
        "usage_events": 1,
    }
