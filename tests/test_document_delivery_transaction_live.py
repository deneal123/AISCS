"""Opt-in real SQL finalization; transport/file-save reuse is mocked, not live PDF acceptance."""

import ast
import asyncio
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,logging,sys,uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.application.documents.publication import service as service
from service.services.chat.persistence.documents import publication as jobs
stage='fixture'; mode=sys.argv[1] if len(sys.argv)>1 else 'rollback'
async def main():
 global stage
 connector=PgConnector(Config().pg); identity=uuid.uuid4().hex; fixture=None; owner=None
 try:
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   file_id=await db.scalar(text('SELECT id FROM profile.user_file WHERE user_id=:owner '
    'ORDER BY created_at DESC LIMIT 1'),{'owner':owner})
   assert file_id is not None
   file_count=await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
    {'owner':owner})
   rows=await jobs.enqueue(db,user_id=owner,thread_id=identity,workspace_id=identity,
    billing_job_id=identity,attach_to_latest=False,descriptors=({
     'build_id':identity,'artifact_id':identity,'role':'pdf','source_digest':'a'*64,
     'artifact_sha256':'b'*64,'artifact_size':4,'filename':'acceptance.pdf',
     'mime_type':'application/pdf'},))
   fixture=rows[0]['id']
   token=uuid.uuid4()
   # The fixture is committed for rollback/reconnect, but cannot be claimed by
   # main workers: a long live lease and future attempt time protect it.
   await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
    "lease_expires_at=clock_timestamp()+interval '600 seconds',"
    "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id"),
    {'token':token,'id':fixture})
   await db.commit()
  downloaded=SimpleNamespace(chunks=lambda:object(),close=AsyncMock())
  files=SimpleNamespace(save_stream=AsyncMock(return_value=SimpleNamespace(file_id=file_id)))
  attach=AsyncMock(side_effect=RuntimeError('private-finalization-marker')
   if mode=='rollback' else None)
  invalidate=AsyncMock()
  @asynccontextmanager
  async def lease(*_args): yield asyncio.Event()
  with (
   patch.object(service,'_settle_pending_audit',AsyncMock()),
   patch.object(service,'read_binding',AsyncMock(return_value={'workspace_id':identity})),
   patch.object(service,'_agent_ref',lambda *_:{}),
   patch.object(service,'_renewing_publication_lease',lease),
   patch.object(service,'_ensure_audited_durable',AsyncMock(return_value='ready')),
   patch.object(service,'document_build_status',AsyncMock(return_value={'state':'ready'})),
   patch.object(service,'_matching_artifact',lambda *_:True),
   patch.object(service,'stream_document_artifact',AsyncMock(return_value=downloaded)),
   patch.object(service,'_attach_generated_file',attach),
   patch('service.services.chat.application.workspace_event_projection.'
    'publish_workspace_invalidation',invalidate),
  ):
   async def read(db):
    return dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
     'WHERE id=:id AND user_id=:owner'),{'id':fixture,'owner':owner})).mappings().one())
   if mode=='commit_loss':
    stage='commit_loss'
    async with connector.get_session_context() as db:
     class LostCommitAcknowledgement:
      def __getattr__(self,name): return getattr(db,name)
      async def commit(self):
       await db.commit()
       raise RuntimeError('private-commit-ack-marker')
     assert await service.deliver_one(config=Config(),pg_connector=connector,redis=object(),
      file_service=files,session=LostCommitAcknowledgement(),row=await read(db))=='deferred'
     await db.commit()
    async with connector.get_session_context() as db:
     committed=await read(db)
     assert committed['status']=='delivered' and committed['user_file_id']==file_id
     assert committed['lease_token'] is None and committed['attempts']==0
     assert committed['failure_code'] is None
     assert await db.scalar(text("SELECT count(*) FROM profile.document_publication_job "
      "WHERE id=:id AND status IN ('pending_audit','pending_delivery')"),{'id':fixture})==0
     assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
      {'owner':owner})==file_count
    assert files.save_stream.await_count==1 and attach.await_count==1
    assert invalidate.await_count==0 and downloaded.close.await_count==1
    return {'committed_delivery_preserved':True,'not_requeued':True,
     'one_file_save':True,'file_count_unchanged':True}
   stage='failed_finalization'
   async with connector.get_session_context() as db:
    row=await read(db)
    outcome=await service.deliver_one(config=Config(),pg_connector=connector,redis=object(),
     file_service=files,session=db,row=row)
    assert outcome=='deferred'; await db.commit()
   async with connector.get_session_context() as db:
    failed=await read(db)
    assert failed['status']=='pending_delivery' and failed['attempts']==1
    assert failed['user_file_id'] is None and failed['lease_token'] is None
    assert failed['failure_code']=='unavailable'
    assert invalidate.await_count==0
    stage='retry'
    new_token=uuid.uuid4()
    await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
     "lease_expires_at=clock_timestamp()+interval '600 seconds' WHERE id=:id"),
     {'token':new_token,'id':fixture})
    await db.commit()
   attach.side_effect=None
   async with connector.get_session_context() as db:
    assert await service.deliver_one(config=Config(),pg_connector=connector,redis=object(),
     file_service=files,session=db,row=await read(db))=='delivered'
   async with connector.get_session_context() as db:
    completed=await read(db)
    assert completed['status']=='delivered' and completed['user_file_id']==file_id
    assert invalidate.await_count==1 and downloaded.close.await_count==2
    intents=[call.kwargs['upload_intent_id'] for call in files.save_stream.await_args_list]
    assert len(intents)==2 and intents[0]==intents[1]
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
     {'owner':owner})==file_count
  return {'rollback_before_retry':True,'retry_delivered':True,'same_upload_intent':True,
   'file_count_unchanged':True}
 finally:
  if fixture is not None:
   original_stage=stage
   stage='cleanup'
   async with connector.get_session_context() as db:
    await db.execute(text('DELETE FROM profile.document_publication_job WHERE id=:id '
     'AND user_id=:owner AND build_id=:build'),{'id':fixture,'owner':owner,'build':identity})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':fixture})==0
   stage=original_stage
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_delivery_transaction_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_PUBLICATION_REPLAY") != "1", reason="dev SQL acceptance")
async def test_metadata_failure_rolls_back_delivery_and_retry_reuses_intent():
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
    assert result.returncode == 0, (
        f"delivery transaction failed at {report.get('stage', 'unknown')}"
    )
    assert report == {
        "status": "passed",
        "checks": {
            "rollback_before_retry": True,
            "retry_delivered": True,
            "same_upload_intent": True,
            "file_count_unchanged": True,
        },
    }


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_PUBLICATION_REPLAY") != "1", reason="dev SQL acceptance")
async def test_lost_commit_acknowledgement_does_not_rewind_delivered_outbox():
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-", "commit_loss"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=45,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "commit acknowledgement report missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, (
        f"delivery commit recovery failed at {report.get('stage', 'unknown')}"
    )
    assert report == {
        "status": "passed",
        "checks": {
            "committed_delivery_preserved": True,
            "not_requeued": True,
            "one_file_save": True,
            "file_count_unchanged": True,
        },
    }
