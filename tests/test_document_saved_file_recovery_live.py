"""Opt-in SQL recovery: committed Library row, absent workspace, no storage/provider calls."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/services/chat/application/documents/publication/service.py",
    "service/services/chat/persistence/documents/publication.py",
    "service/services/chat/persistence/documents/audit/attempts.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.application.documents.publication import service as service
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.persistence.documents.audit import attempts as attempts

stage='source_parity'; cleaned=False
async def main():
 global stage,cleaned
 for module,expected in zip((service,jobs,attempts),sys.argv[1:],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 external=uuid.uuid4(); thread_pk=None; job_ids=[]; file_ids=[]; owner=None; checks={}
 try:
  stage='fixture'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   other=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None and other is not None and owner!=other
   thread_pk=await db.scalar(text('INSERT INTO profile.chat_threads '
    '(thread_id,user_id,title,created_at,updated_at) '
    'VALUES (:thread,:owner,\'saved delivery acceptance\',now(),now()) RETURNING id'),
    {'thread':external,'owner':owner})
   message=await db.scalar(text('INSERT INTO profile.chat_messages '
    '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
    'VALUES (:message,:thread,:owner,\'assistant\',\'synthetic fixture\','
    'CAST(:meta AS JSONB),now()) RETURNING id'),
    {'message':uuid.uuid4(),'thread':thread_pk,'owner':owner,
     'meta':json.dumps({'document_outcome':'deferred','model':'author-model','keep':1})})
   for role in ('pdf','source_bundle'):
    identity=uuid.uuid4().hex
    created=await jobs.enqueue(db,user_id=owner,thread_id=str(external),workspace_id=identity,
     billing_job_id=identity,descriptors=({'build_id':identity,'artifact_id':identity,'role':role,
      'source_digest':'b'*64,'artifact_sha256':'a'*64,'artifact_size':4,
      'filename':'final.pdf' if role=='pdf' else 'sources.zip',
      'mime_type':'application/pdf' if role=='pdf' else 'application/zip'},))
    job_id=created[0]['id']; job_ids.append(job_id)
    token=uuid.uuid4()
    await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
     "lease_expires_at=clock_timestamp()+interval '600 seconds',"
     "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
     {'id':job_id,'owner':owner,'token':token})
    row=dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':job_id})).mappings().one())
    file_id=uuid.uuid4(); file_ids.append(file_id)
    await db.execute(text('INSERT INTO profile.user_file '
     '(id,user_id,mode,file_name,original_name,upload_intent_id,'
     'content_sha256,file_url,created_at) '
     'VALUES (:id,:owner,\'CHAT\',:key,:name,:intent,:sha,:url,now())'),
     {'id':file_id,'owner':owner,'key':'acceptance/'+identity,'name':row['filename'],
      'intent':jobs.upload_intent(row),'sha':row['artifact_sha256'],'url':'synthetic://artifact'})
   await db.commit()

  async with connector.get_session_context() as db:
   stage='owner_and_integrity'
   pdf=dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
    'WHERE id=:id'),{'id':job_ids[0]})).mappings().one())
   assert await jobs.saved_file_id(db,{**pdf,'user_id':other}) is None
   for field,value in (('filename','other.pdf'),('artifact_sha256','c'*64)):
    try: await jobs.saved_file_id(db,{**pdf,field:value})
    except jobs.PublicationArtifactMismatch: pass
    else: raise AssertionError('integrity_not_enforced')
   stage='audit_proof'
   await db.execute(text("UPDATE profile.document_publication_job SET status='pending_audit' "
    'WHERE id=:id'),{'id':job_ids[0]})
   assert await jobs.saved_file_id(db,pdf) is None
   audit_id=uuid.uuid4()
   await db.execute(text('INSERT INTO profile.document_audit_attempt '
    '(id,publication_job_id,user_id,build_id,source_digest,artifact_sha256,state,charge_id,'
    'failure_code,usage_envelope,created_at,settled_at) VALUES '
    '(:id,:job,:owner,:build,:source,:sha,\'settled\',\'no_usage\',NULL,\'{}\'::jsonb,now(),now())'),
    {'id':audit_id,'job':pdf['id'],'owner':owner,'build':pdf['build_id'],
     'source':pdf['source_digest'],'sha':pdf['artifact_sha256']})
   assert await jobs.saved_file_id(db,pdf)==file_ids[0]
   for field,value in (('failure_code','audit_failed'),('state','charge_pending'),
    ('source_digest','d'*64),('artifact_sha256','e'*64),('charge_id',None)):
    await db.execute(text('SAVEPOINT audit_check'))
    await db.execute(text('UPDATE profile.document_audit_attempt '
     'SET '+field+'=:value WHERE id=:id'),
     {'value':value,'id':audit_id})
    assert await jobs.saved_file_id(db,pdf) is None
    await db.execute(text('ROLLBACK TO SAVEPOINT audit_check'))
   await db.execute(text("UPDATE profile.document_audit_attempt "
    "SET failure_code='attestation_pending' WHERE id=:id"),{'id':audit_id})
   await db.commit(); checks['owner_digest_audit_bound']=True
   stage='attestation_confirmation'
   assert await attempts.attestation_pending(db,pdf)
   assert await jobs.saved_file_id(db,pdf) is None
   ready={'state':'ready','build_id':pdf['build_id'],'source_digest':pdf['source_digest'],
    'artifacts':[{'artifact_id':pdf['artifact_id'],'sha256':pdf['artifact_sha256'],
     'size':pdf['artifact_size'],'mime_type':pdf['mime_type']}]}
   forbidden_audit=AsyncMock(side_effect=AssertionError('visual_repeated'))
   with patch.object(service,'audit_document',forbidden_audit):
    with patch.object(service,'document_build_status',
     AsyncMock(return_value={**ready,'source_digest':'e'*64})):
     assert await service._ensure_audited_durable(config=cfg,pg_connector=connector,
      redis=object(),session=db,ref={},row=pdf)=='artifact_mismatch'
    assert await jobs.saved_file_id(db,pdf) is None
    with patch.object(service,'document_build_status',AsyncMock(return_value=ready)):
     assert await service._ensure_audited_durable(config=cfg,pg_connector=connector,
      redis=object(),session=db,ref={},row=pdf)=='ready'
    forbidden_audit.assert_not_awaited()
   assert not await attempts.attestation_pending(db,pdf)
   assert await jobs.saved_file_id(db,pdf)==file_ids[0]
   checks['ready_attestation_bound']=True

  binding=AsyncMock(return_value=None); audit=AsyncMock(); stream=AsyncMock()
  files=SimpleNamespace(save_stream=AsyncMock()); invalidate=AsyncMock()
  with (
   patch.object(service,'read_binding',binding),
   patch.object(service,'_ensure_audited_durable',audit),
   patch.object(service,'stream_document_artifact',stream),
   patch('service.services.chat.application.workspace_event_projection.'
    'publish_workspace_invalidation',invalidate),
  ):
   for job_id in job_ids:
    stage='recovered_delivery'
    async with connector.get_session_context() as db:
     row=dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
      'WHERE id=:id'),{'id':job_id})).mappings().one())
     assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=files,session=db,row=row)=='delivered'
     assert await jobs.saved_file_id(db,row) in file_ids
    stage='replay'
    async with connector.get_session_context() as db:
     row=dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
      'WHERE id=:id'),{'id':job_id})).mappings().one())
     assert row['lease_token'] is None
     assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=files,session=db,row=row)=='delivered'
     await db.commit()
     observed=(await db.execute(text('SELECT status,user_file_id,attempts FROM '
      'profile.document_publication_job WHERE id=:id'),{'id':job_id})).one()
     assert observed[0]=='delivered' and observed[1] in file_ids and observed[2]==0
   binding.assert_not_awaited()
   audit.assert_not_awaited(); stream.assert_not_awaited(); files.save_stream.assert_not_awaited()
   assert invalidate.await_count==2
  async with connector.get_session_context() as db:
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':message})
   assert {item['file_id'] for item in metadata['generated_files']}=={
    str(item) for item in file_ids}
   assert metadata['document_outcome']=='completed' and metadata['model']=='author-model'
   assert metadata['keep']==1
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE id=ANY(:ids)'),
    {'ids':file_ids})==2
   checks['one_owned_file_per_role']=True; checks['projection_preserved']=True
 finally:
  original_stage=stage; stage='cleanup'
  async with connector.get_session_context() as db:
   if job_ids:
    await db.execute(text('DELETE FROM profile.document_publication_job '
     'WHERE id=ANY(:ids) AND user_id=:owner'),{'ids':job_ids,'owner':owner})
   if file_ids:
    await db.execute(text('DELETE FROM profile.user_file WHERE id=ANY(:ids) AND user_id=:owner'),
     {'ids':file_ids,'owner':owner})
   if thread_pk is not None:
    await db.execute(text('DELETE FROM profile.chat_threads '
     'WHERE id=:id AND user_id=:owner AND thread_id=:thread'),
     {'id':thread_pk,'owner':owner,'thread':external})
   await db.commit()
   for table,ids in (('document_publication_job',job_ids),('user_file',file_ids)):
    if ids:
     assert await db.scalar(text('SELECT count(*) FROM profile.'+table+' WHERE id=ANY(:ids)'),
      {'ids':ids})==0
   if thread_pk is not None:
    assert await db.scalar(text('SELECT count(*) FROM profile.chat_threads WHERE id=:id'),
     {'id':thread_pk})==0
   cleaned=True
  await connector.close(); stage=original_stage
 print(json.dumps({'status':'passed','checks':checks,'fixture_cleaned':cleaned}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','stage':stage,'fixture_cleaned':cleaned})); raise SystemExit(1)
"""


def test_saved_file_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_SAVED_FILE_RECOVERY") != "1", reason="opt-in isolated dev PostgreSQL"
)
def test_saved_file_recovers_delivery_after_workspace_expiry():
    expected = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-", *expected],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "bounded saved-file recovery report missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, f"saved-file proof failed at {report.get('stage', 'unknown')}"
    assert report == {
        "status": "passed",
        "fixture_cleaned": True,
        "checks": {
            "owner_digest_audit_bound": True,
            "ready_attestation_bound": True,
            "one_owned_file_per_role": True,
            "projection_preserved": True,
        },
    }
