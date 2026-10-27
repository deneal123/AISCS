"""Opt-in real agents HTTP/Redis -> owned PostgreSQL recovery; no paid calls."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_SETUP = """
import asyncio,json,logging,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.persistence.documents.audit import attempts as attempts
async def main():
 db=PgConnector(config.pg)
 try:
  async with db.get_session_context() as s:
   owner=await s.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
     {'email':'s38-video-acceptance@example.com'}); assert owner
   identity=str(uuid.uuid4()); workspace='recovery-'+identity
   rows=await jobs.enqueue(s,user_id=owner,thread_id=workspace,workspace_id=workspace,
     billing_job_id=workspace,attach_to_latest=False,descriptors=({'build_id':identity,
      'artifact_id':identity,'role':'pdf','source_digest':'a'*64,'artifact_sha256':'b'*64,
      'artifact_size':1,'filename':'recovery-fixture.pdf','mime_type':'application/pdf'},))
   row=dict(rows[0]); row.update(user_id=owner,build_id=identity,
      source_digest='a'*64,artifact_sha256='b'*64)
   await s.execute(text('UPDATE profile.document_publication_job SET status=:status WHERE id=:id'),
     {'id':row['id'],'status':'terminal'})
   attempt=await attempts.begin(s,row); assert attempt['may_execute'] is True
   await s.commit()
   print(json.dumps({'id':str(row['id']),'user_id':str(owner),'workspace_id':workspace,
     'build_id':identity,'source_digest':'a'*64,'artifact_sha256':'b'*64,
     'attempt_id':str(attempt['id'])}))
 finally: await db.close()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""

_SEED = """
import asyncio,json,logging,sys,os,signal
logging.disable(logging.CRITICAL)
from service.presentation.routers.capabilities.document_audit import DocumentAuditRequest
from service.presentation.routers.capabilities.managed_document_audit import registry_for
p=json.load(sys.stdin)
async def main():
 request=DocumentAuditRequest(build_id=p['build_id'],workspace_ref={
   'user_id':p['user_id'],'workspace_id':p['workspace_id']},checkpoint_attempt_id=p['attempt_id'])
 registry=registry_for(request)
 try:
  assert await registry.claim(fresh_attempt=True)
  await registry.checkpoint({'schema_version':1,'attempt_id':p['attempt_id'],'revision':1,
   'receipts':[{'receipt_id':'fixture-call','provider':'gigachat','model':'GigaChat-2-Max',
    'kind':'document_visual_audit','prompt':30,'completion':3,'estimated':False}]})
  if p.get('interrupted'):
   assert os.getpid()>1
   print(json.dumps({'status':'checkpointed'}),flush=True)
   os.kill(os.getpid(),signal.SIGKILL)
  await registry.seal({'status':'failed','passed':False,'retryable':False})
  print(json.dumps({'status':'seeded'}))
 finally: await registry.redis.aclose()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""

_RECOVER = """
import asyncio,json,logging,sys,uuid,hashlib
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from pathlib import Path
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.application.documents.audit.recovery import recover_started_result
from service.services.chat.application.documents.audit.reconciliation import reconcile_started_audit
from service.services.chat.persistence.documents.audit import attempts as attempts
p=json.load(sys.stdin)
assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest
 for name,digest in p['source_hashes'].items())
async def main():
 db=PgConnector(config.pg)
 try:
  async with db.get_session_context() as s:
   result=await s.execute(text('SELECT * FROM profile.document_publication_job '
      'WHERE id=:id AND user_id=:owner AND status=:state'),
     {'id':uuid.UUID(p['id']),'owner':uuid.UUID(p['user_id']),'state':'terminal'})
   row=dict(result.mappings().one()); attempt=uuid.UUID(p['attempt_id'])
   ref={'user_id':p['user_id'],'workspace_id':p['workspace_id']}
   settlements=[]
   async def settle_pending(**kwargs):
    pending=await attempts.pending_charge(s,row)
    assert pending and pending['id']==attempt and pending['usage_envelope']['total']==33
    expected_failure='audit_unavailable' if p.get('interrupted') else 'audit_failed'
    assert pending['failure_code']==expected_failure
    settlements.append(True)
    assert await attempts.settle(s,attempt_id=attempt,charge_id='acceptance:no-monetary-charge')
    await s.commit()
   assert await reconcile_started_audit(config,db,None,s,row,settle_pending)
   assert await reconcile_started_audit(config,db,None,s,row,settle_pending)
   assert settlements==[True]
   assert await recover_started_result(config=config,session=s,row=row,ref=ref,
     attempt_id=attempt) is None
   assert not await attempts.settle(s,attempt_id=attempt,charge_id='replay')
   await s.rollback()
   print(json.dumps({'status':'passed','tokens':33,'receipts':1,'settled_once':True}))
 finally: await db.close()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""

_CLEAN_DB = """
import asyncio,json,logging,sys,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
p=json.load(sys.stdin)
async def main():
 db=PgConnector(config.pg)
 try:
  async with db.get_session_context() as s:
   await s.execute(text('DELETE FROM profile.document_publication_job '
    'WHERE id=:id AND user_id=:owner '
    'AND workspace_id=:workspace AND status=:state'),{'id':uuid.UUID(p['id']),
    'owner':uuid.UUID(p['user_id']),'workspace':p['workspace_id'],'state':'terminal'})
   await s.commit()
   assert await s.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':uuid.UUID(p['id'])})==0
   assert await s.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
     'WHERE publication_job_id=:id'),{'id':uuid.UUID(p['id'])})==0
   print(json.dumps({'status':'cleaned'}))
 finally: await db.close()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""

_CLEAN_REDIS = """
import asyncio,json,logging,sys
logging.disable(logging.CRITICAL)
from service.presentation.routers.capabilities.document_audit import DocumentAuditRequest
from service.presentation.routers.capabilities.managed_document_audit import registry_for
p=json.load(sys.stdin)
async def main():
 registry=registry_for(DocumentAuditRequest(build_id=p['build_id'],workspace_ref={
  'user_id':p['user_id'],'workspace_id':p['workspace_id']},checkpoint_attempt_id=p['attempt_id']))
 try:
  current=await registry.read()
  if current is not None: assert await registry.redis.delete(registry.key)==1
  assert await registry.read() is None
  print(json.dumps({'status':'cleaned'}))
 finally: await registry.redis.aclose()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""


def _run(container, program, payload=None, *, expected_code=0):
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", program],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=45,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert result.returncode == expected_code and lines, "private_recovery_probe_failed"
    return json.loads(lines[-1])


def test_probes_are_valid_python():
    for program in (_SETUP, _SEED, _RECOVER, _CLEAN_DB, _CLEAN_REDIS):
        ast.parse(program)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_AUDIT_RECOVERY") != "1", reason="opt-in owned dev HTTP/SQL/Redis"
)
@pytest.mark.parametrize("interrupted", [False, True])
def test_live_private_recovery_imports_known_receipt_and_settles_once(interrupted):
    fixture = _run("gpthub-dev-backend-1", _SETUP)
    fixture["interrupted"] = interrupted
    fixture["source_hashes"] = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in (
            "service/infrastructure/agents_client/document_audit/recovery.py",
            "service/services/chat/application/documents/audit/recovery.py",
            "service/services/chat/application/documents/audit/reconciliation.py",
            "service/services/chat/persistence/documents/audit/attempts.py",
            "service/services/chat/persistence/documents/audit/checkpoint.py",
        )
    }
    try:
        seeded = _run(
            "gpthub-dev-agents-1", _SEED, fixture, expected_code=137 if interrupted else 0
        )
        assert seeded == {"status": "checkpointed" if interrupted else "seeded"}
        assert _run("gpthub-dev-backend-1", _RECOVER, fixture) == {
            "status": "passed",
            "tokens": 33,
            "receipts": 1,
            "settled_once": True,
        }
    finally:
        try:
            assert _run("gpthub-dev-agents-1", _CLEAN_REDIS, fixture) == {"status": "cleaned"}
        finally:
            assert _run("gpthub-dev-backend-1", _CLEAN_DB, fixture) == {"status": "cleaned"}
