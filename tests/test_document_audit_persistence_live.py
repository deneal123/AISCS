"""Opt-in real PostgreSQL reconnect test; no provider calls or monetary charges."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_AUDIT_PERSISTENCE") != "1", reason="dev PostgreSQL")
@pytest.mark.parametrize("process_exit", [False, True])
@pytest.mark.parametrize("receipt_count", [1, 50])
async def test_charge_pending_survives_connection_close_and_settles_once(
    process_exit, receipt_count
):
    probe = """
import asyncio,json,logging,uuid,os,sys,hashlib
from pathlib import Path
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.persistence.documents.audit import attempts as attempts
from service.infrastructure.agents_client.document_audit import client as document_audit
logging.disable(logging.CRITICAL)
assert hashlib.sha256(Path(document_audit.__file__).read_bytes()).hexdigest()=='__AUDIT_DIGEST__'
usage=document_audit._bounded_usage({'calls':[
 {'receipt_id':'fixture-'+str(index),'model':'GigaChat-2-Max','provider':'gigachat',
  'prompt':30,'completion':3,'estimated':bool(index%2)}
 for index in range(__RECEIPT_COUNT__)]*2})
assert len(usage['calls'])==__RECEIPT_COUNT__ and usage['total']==33*__RECEIPT_COUNT__
identity=str(uuid.uuid4())
async def main(mode='standard'):
 connector=PgConnector(Config().pg); job_id=None
 try:
  owner=await ProfileRepository(connector).fetch_user_by_email(
   's37-e2e-391e5206659a3654@example.com')
  if mode=='recover':
   async with connector.get_session_context() as session:
    result=await session.execute(text('SELECT * FROM profile.document_publication_job '
     'WHERE workspace_id=:workspace AND user_id=:owner AND status=:state'),
     {'workspace':'s37-db-'+identity,'owner':owner.id,'state':'terminal'})
    rows=list(result.mappings()); assert len(rows)==1
    row=dict(rows[0]); job_id=row['id']
    attempt=await attempts.pending_charge(session,row)
    assert attempt is not None
  else:
   async with connector.get_session_context() as session:
    rows=await jobs.enqueue(session,user_id=owner.id,thread_id='s37-db-'+identity,
     workspace_id='s37-db-'+identity,billing_job_id='s37-db-'+identity,
     attach_to_latest=False,descriptors=({
      'build_id':identity,'artifact_id':identity,'role':'pdf',
      'source_digest':'a'*64,'artifact_sha256':'b'*64,'artifact_size':1,
      'filename':'s37-persistence-fixture.pdf','mime_type':'application/pdf'},))
    row=dict(rows[0]); job_id=row['id']
    row.update(user_id=owner.id,build_id=identity,source_digest='a'*64,artifact_sha256='b'*64)
    # Terminal fixture prevents the background outbox from claiming synthetic work.
    await session.execute(text(
     'UPDATE profile.document_publication_job SET status=:state WHERE id=:id'),
     {'id':job_id,'state':'terminal'})
    attempt=await attempts.begin(session,row)
    await attempts.record_result(session,attempt_id=attempt['id'],
     usage=usage)
    await session.commit()
   if mode=='produce':
    os._exit(73)
  async with connector.get_session_context() as session:
   pending=await attempts.pending_charge(session,row)
   assert pending and pending['id']==attempt['id'] and pending['usage_envelope']==usage
   assert await attempts.settle(session,attempt_id=pending['id'],
    charge_id='acceptance:no-monetary-charge')
   await session.commit()
  async with connector.get_session_context() as session:
   assert await attempts.pending_charge(session,row) is None
   assert not await attempts.settle(session,attempt_id=attempt['id'],charge_id='replay')
   await session.rollback()
  print(json.dumps({'reconnected':True,'usage_retained':True,'settled_once':True}))
 finally:
  if job_id is not None:
   async with connector.get_session_context() as session:
    await session.execute(text('DELETE FROM profile.document_publication_job WHERE id=:id'),
     {'id':job_id})
    await session.commit()
    remaining=await session.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':job_id})
    orphaned=await session.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
     'WHERE publication_job_id=:id'),{'id':job_id})
    assert remaining==0 and orphaned==0
if len(sys.argv)>1 and sys.argv[1]=='process-exit':
 pid=os.fork()
 if pid==0:
  asyncio.run(main('produce'))
  os._exit(74)
 _,status=os.waitpid(pid,0)
 assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==73
 asyncio.run(main('recover'))
else:
 asyncio.run(main())
"""
    probe = probe.replace("__RECEIPT_COUNT__", str(receipt_count)).replace(
        "__AUDIT_DIGEST__",
        hashlib.sha256(
            Path("service/infrastructure/agents_client/document_audit/client.py").read_bytes()
        ).hexdigest(),
    )
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"]
        + (["process-exit"] if process_exit else []),
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail("audit_persistence_probe_failed")
    assert json.loads(result.stdout) == {
        "reconnected": True,
        "usage_retained": True,
        "settled_once": True,
    }
