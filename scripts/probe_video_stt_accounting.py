"""Read-only isolated dev accounting aggregates; no IDs or payload output."""

from __future__ import annotations

import json
import subprocess

SOURCE = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text,select,func
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.services.billing.application.billing_service import BillingService
from service.services.billing.persistence.billing_repository import BillingRepository
from service.infrastructure.cache.manager import RedisManager
async def main():
 db=PgConnector(config.pg,force_new=True)
 redis=RedisManager(config.redis)
 try:
  user=await ProfileRepository(db).fetch_user_by_email('s38-video-acceptance@example.com')
  if user is None: raise ValueError
  async with db.get_session_context() as session:
   rows=(await session.execute(text(
    "SELECT tokens,metadata FROM profile.billing_events WHERE user_id=:owner "
    "AND event_type='usage' AND created_at>=now()-interval '30 minutes'"),
    {'owner':user.id})).all()
   active_jobs=await session.scalar(select(func.count()).select_from(UserLaunch).where(
    UserLaunch.user_id==user.id,
    UserLaunch.status.in_([ProcessingStatus.NEW,ProcessingStatus.PROCESSING])))
  calls=[call for _,meta in rows for call in meta.get('per_call',[])]
  providers={call.get('provider') for call in calls}
  grants=0
  client=redis.get_client()
  async for key in client.scan_iter(match='video:stt:grant:*'):
   binding=json.loads(await client.get(key) or '{}')
   grants+=binding.get('owner_id')==str(user.id)
  print(json.dumps({'status':'ready','charge_count':len(rows),
   'credits':sum(meta.get('from_subscription',0)+meta.get('from_topup',0) for _,meta in rows),
   'receipt_count':len(calls),'tokens':sum(tokens or 0 for tokens,_ in rows),
   'event_metadata_keys':[sorted(meta) for _,meta in rows],
   'tool_counts':[len(meta.get('tools',[])) for _,meta in rows],
   'owned_stt_grants':grants,
   'owned_nonterminal_jobs':active_jobs,
   'billing_fallbacks':[meta.get('billing_fallback') in {'no_provider_usage_floor','pricing_failed_floor'} for _,meta in rows],
   'all_receipts_gigachat':bool(calls) and providers=={'gigachat'},
   'all_models_gigachat_2':bool(calls) and all(call.get('model')=='GigaChat-2' for call in calls),
   'transcription_charges':sum(meta.get('kind')=='transcription' for _,meta in rows),
   'memory_calls':sum(call.get('kind')=='memory' for call in calls),
   'balance':(await BillingService(BillingRepository(db),config.billing).get_balance(str(user.id))).total}))
 finally:
  await redis.close()
  await db.close()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'unavailable','code':'accounting_probe_failed'}))
"""


def main() -> None:
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
            input=SOURCE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        report = json.loads(result.stdout) if result.returncode == 0 else None
        if not isinstance(report, dict):
            raise ValueError
        print(json.dumps(report))
    except Exception:
        print(json.dumps({"status": "unavailable", "code": "accounting_probe_failed"}))


if __name__ == "__main__":
    main()
