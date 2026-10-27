"""Opt-in SQL replay proof; uncommitted fixtures cannot be claimed by workers."""

import ast
import asyncio
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,logging,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.persistence.documents.publication import enqueue,delivered,renew,defer
stage='fixture'
async def main():
 global stage
 connector=PgConnector(Config().pg)
 identity=uuid.uuid4().hex
 async with connector.get_session_context() as db:
  owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
   {'email':'s37-e2e-391e5206659a3654@example.com'})
  assert owner is not None
  descriptor={'build_id':identity,'artifact_id':identity,'role':'pdf',
   'source_digest':'a'*64,'artifact_sha256':'b'*64,'artifact_size':1,
   'filename':'acceptance.pdf','mime_type':'application/pdf',
   'initial_status':'pending_audit'}
  kwargs={'user_id':owner,'thread_id':identity,'workspace_id':identity,
   'billing_job_id':identity,'descriptors':(descriptor,),'attach_to_latest':False}
  inserted=await enqueue(db,**kwargs); assert len(inserted)==1
  job=inserted[0]['id']; token=uuid.uuid4()
  stage='replay'
  try:
   for state in ('pending_audit','pending_delivery','delivered','terminal'):
    await db.execute(text("UPDATE profile.document_publication_job SET status=:state, "
     "attempts=3,next_attempt_at=now()+interval '1 hour',lease_token=:token,"
     "lease_expires_at=now()+interval '120 seconds',failure_code='unavailable' "
     "WHERE id=:id"),{'state':state,'token':token,'id':job})
    async def read():
     return dict((await db.execute(text('SELECT id,status,attempts,next_attempt_at,'
      'lease_token,lease_expires_at,failure_code,artifact_sha256 '
      'FROM profile.document_publication_job WHERE id=:id'),{'id':job})).mappings().one())
    before=await read()
    repeated=await enqueue(db,**kwargs)
    assert len(repeated)==1 and repeated[0]['id']==job
    assert await read()==before
   assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
    'WHERE user_id=:owner AND build_id=:build'),{'owner':owner,'build':identity})==1
   stage='lease_fencing'
   file_id=await db.scalar(text('SELECT id FROM profile.user_file WHERE user_id=:owner '
    'ORDER BY created_at DESC LIMIT 1'),{'owner':owner})
   assert file_id is not None
   await db.execute(text("UPDATE profile.document_publication_job SET status='pending_delivery', "
    "lease_expires_at=transaction_timestamp()+interval '1 microsecond' WHERE id=:id"),{'id':job})
   # now() remains the old transaction timestamp during a long stream. Prove
   # the expiry sits after that timestamp but before actual completion time.
   assert await db.scalar(text('SELECT lease_expires_at>transaction_timestamp() '
    'AND lease_expires_at<clock_timestamp() FROM profile.document_publication_job '
    'WHERE id=:id'),{'id':job})
   stage='expired_delivery_admitted'
   assert not await delivered(db,job_id=job,lease_token=token,file_id=file_id)
   assert not await renew(db,job_id=job,lease_token=token)
   assert not await defer(db,job_id=job,lease_token=token,failure_code='unavailable')
   stage='replacement_lease_fencing'
   await db.execute(text("UPDATE profile.document_publication_job SET "
    "lease_token=:replacement,lease_expires_at=clock_timestamp()+interval '120 seconds' "
    "WHERE id=:id"),{'replacement':uuid.uuid4(),'id':job})
   assert not await delivered(db,job_id=job,lease_token=token,file_id=file_id)
   assert not await renew(db,job_id=job,lease_token=token)
   assert not await defer(db,job_id=job,lease_token=token,failure_code='unavailable')
   stage='terminal_lease_fencing'
   await db.execute(text("UPDATE profile.document_publication_job SET "
    "lease_token=:token,status='terminal' WHERE id=:id"),{'token':token,'id':job})
   assert not await delivered(db,job_id=job,lease_token=token,file_id=file_id)
   assert not await renew(db,job_id=job,lease_token=token)
   assert not await defer(db,job_id=job,lease_token=token,failure_code='unavailable')
   stage='valid_delivery'
   await db.execute(text("UPDATE profile.document_publication_job SET "
    "status='pending_delivery' WHERE id=:id"),{'id':job})
   assert await renew(db,job_id=job,lease_token=token)
   assert await delivered(db,job_id=job,lease_token=token,file_id=file_id)
   stage='delivered_replay'
   assert not await delivered(db,job_id=job,lease_token=token,file_id=file_id)
   assert not await renew(db,job_id=job,lease_token=token)
  finally:
   await db.rollback()
  stage='cleanup'
  assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
   'WHERE user_id=:owner AND build_id=:build'),{'owner':owner,'build':identity})==0
 return {'replay_preserved':True,'single_row':True,'expired_lease_rejected':True,
  'replacement_lease_rejected':True,'terminal_preserved':True,'valid_delivery':True,
  'rollback_cleanup':True}
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_publication_replay_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_PUBLICATION_REPLAY") != "1", reason="dev SQL acceptance")
async def test_enqueue_replay_preserves_delivery_state_backoff_and_lease():
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=45,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "bounded acceptance report missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, f"publication replay failed at {report.get('stage', 'unknown')}"
    assert report == {
        "status": "passed",
        "checks": {
            "replay_preserved": True,
            "single_row": True,
            "expired_lease_rejected": True,
            "replacement_lease_rejected": True,
            "terminal_preserved": True,
            "valid_delivery": True,
            "rollback_cleanup": True,
        },
    }
