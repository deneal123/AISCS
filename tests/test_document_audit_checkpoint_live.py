"""Opt-in owned PostgreSQL checkpoint/reconnect probe; no provider or charge."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,copy,hashlib,json,logging,uuid
from pathlib import Path
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.persistence.documents.audit import attempts as attempts
from service.services.chat.persistence.documents.audit import checkpoint as checkpoints
from service.infrastructure.agents_client.document_audit import stream as consumer
logging.disable(logging.CRITICAL)
stage='freshness'
async def main():
 global stage
 assert hashlib.sha256(Path(checkpoints.__file__).read_bytes()).hexdigest()=='__DIGEST__'
 assert hashlib.sha256(Path(consumer.__file__).read_bytes()).hexdigest()=='__STREAM_DIGEST__'
 connector=PgConnector(Config().pg); job_id=None
 try:
  stage='setup'
  async with connector.get_session_context() as session:
   owner=await session.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
     {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
   identity=str(uuid.uuid4())
   rows=await jobs.enqueue(session,user_id=owner,thread_id='checkpoint-'+identity,
    workspace_id='checkpoint-'+identity,billing_job_id='checkpoint-'+identity,
    attach_to_latest=False,descriptors=({'build_id':identity,'artifact_id':identity,
     'role':'pdf','source_digest':'a'*64,'artifact_sha256':'b'*64,'artifact_size':1,
     'filename':'checkpoint-fixture.pdf','mime_type':'application/pdf'},))
   row=dict(rows[0]); job_id=row['id']
   row.update(user_id=owner,build_id=identity,source_digest='a'*64,artifact_sha256='b'*64)
   # Never expose synthetic work to the live outbox worker.
   await session.execute(text('UPDATE profile.document_publication_job SET status=:state '
     'WHERE id=:id'),{'id':job_id,'state':'terminal'})
   attempt=await attempts.begin(session,row)
   assert attempt['may_execute'] is True
   assert not await attempts.settle(session,attempt_id=attempt['id'],charge_id='fixture-no-charge')
   payload={'schema_version':1,'attempt_id':str(attempt['id']),'revision':1,'receipts':[{
    'receipt_id':'fixture-call','provider':'gigachat','model':'GigaChat-2-Max',
    'kind':'document_visual_audit','prompt':30,'completion':3,'estimated':True}]}
   assert await checkpoints.stage_checkpoint(session,row=row,payload=payload)
   await session.commit()
  stage='reconnect'
  async with connector.get_session_context() as session:
   resumed=await attempts.begin(session,row)
   assert resumed['id']==attempt['id'] and resumed['may_execute'] is False
   await session.commit()
   stored=await session.scalar(text('SELECT usage_envelope FROM profile.document_audit_attempt '
    'WHERE id=:id'),{'id':attempt['id']})
   assert stored[checkpoints.JOURNAL_KEY]==payload and stored['total']==33
   assert not await checkpoints.stage_checkpoint(session,row=row,payload=payload)
   for key,value in [('user_id',uuid.uuid4()),('source_digest','c'*64),
                     ('artifact_sha256','d'*64),('build_id','different')]:
    try:
     await checkpoints.stage_checkpoint(session,row={**row,key:value},payload=payload)
    except checkpoints.AuditCheckpointUnavailable:
     pass
    else:
     raise AssertionError('ownership_mismatch_admitted')
   refined=copy.deepcopy(payload); refined['revision']=2
   refined['receipts'][0].update(prompt=20,completion=2,estimated=False)
   assert await checkpoints.stage_checkpoint(session,row=row,payload=refined)
   await session.commit()
  stage='consumer_commit'
  streamed=copy.deepcopy(refined); streamed['revision']=3
  second=copy.deepcopy(streamed['receipts'][0])
  second.update(receipt_id='second-call',prompt=30,completion=3)
  streamed['receipts'].append(second)
  async def persist(value):
   async with connector.get_session_context() as session:
    assert await checkpoints.stage_checkpoint(session,row=row,payload=value)
    await session.commit()
  async def frames():
   yield {consumer.CHECKPOINT_KEY:streamed}
   async with connector.get_session_context() as session:
    saved=await session.scalar(text('SELECT usage_envelope FROM profile.document_audit_attempt '
      'WHERE id=:id'),{'id':attempt['id']})
    assert saved['total']==55 and saved[checkpoints.JOURNAL_KEY]==streamed
    await session.rollback()
   yield {consumer.RESULT_KEY:{'status':'unavailable','passed':False,'retryable':True}}
  terminal=await consumer.consume_audit_frames(frames(),attempt_id=attempt['id'],persist=persist)
  assert terminal['status']=='unavailable'
  stage='sealed'
  async with connector.get_session_context() as session:
   stored=await session.scalar(text('SELECT usage_envelope FROM profile.document_audit_attempt '
    'WHERE id=:id'),{'id':attempt['id']})
   assert stored['total']==55 and stored[checkpoints.JOURNAL_KEY]==streamed
   recorded=await attempts.record_merged_result(session,attempt_id=attempt['id'],
     usage={},failure_code='audit_unavailable')
   assert recorded and recorded.usage==stored and recorded.failure_code=='audit_unavailable'
   try:
    await checkpoints.stage_checkpoint(session,row=row,payload=streamed)
   except checkpoints.AuditCheckpointUnavailable:
    pass
   else:
    raise AssertionError('sealed_attempt_admitted')
   await session.commit()
  async with connector.get_session_context() as session:
   sealed=(await session.execute(text('SELECT state,usage_envelope FROM '
    'profile.document_audit_attempt WHERE id=:id'),{'id':attempt['id']})).mappings().first()
   assert sealed['state']=='charge_pending' and sealed['usage_envelope']==stored
   assert await attempts.record_merged_result(session,attempt_id=attempt['id'],usage={}) is None
   await session.rollback()
  print(json.dumps({'status':'passed','reconnected':True,'scope_checks':4,'frozen':True}))
 finally:
  if job_id is not None:
   async with connector.get_session_context() as session:
    await session.execute(text('DELETE FROM profile.document_publication_job WHERE id=:id'),
     {'id':job_id})
    await session.commit()
    assert await session.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
      'WHERE publication_job_id=:id'),{'id':job_id})==0
  await connector.close()
try:
 asyncio.run(main())
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_AUDIT_CHECKPOINT") != "1", reason="opt-in isolated dev PostgreSQL"
)
def test_owned_checkpoint_survives_reconnect_and_freezes():
    source = Path("service/services/chat/persistence/documents/audit/checkpoint.py")
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=_PROBE.replace("__DIGEST__", hashlib.sha256(source.read_bytes()).hexdigest())
        .replace(
            "__STREAM_DIGEST__",
            hashlib.sha256(
                Path("service/infrastructure/agents_client/document_audit/stream.py").read_bytes()
            ).hexdigest(),
        )
        .encode(),
        capture_output=True,
        timeout=60,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "audit_checkpoint_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "audit_checkpoint_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report == {"status": "passed", "reconnected": True, "scope_checks": 4, "frozen": True}
