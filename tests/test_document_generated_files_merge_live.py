"""Opt-in dev PostgreSQL proof of concurrent assistant artifact projection."""

import ast
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[1] / (
    "service/services/chat/application/documents/publication/service.py"
)
_REPOSITORY = Path(__file__).resolve().parents[1] / (
    "service/services/chat/persistence/documents/publication.py"
)
_PROBE = r"""
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.application.documents.publication import service as service
from service.services.chat.persistence.documents.publication import enqueue
from service.services.chat.persistence.documents import publication as document_publications
stage='freshness'
cleaned=False
async def main():
 global stage,cleaned
 assert hashlib.sha256(Path(service.__file__).read_bytes()).hexdigest()==sys.argv[1]
 assert hashlib.sha256(Path(document_publications.__file__).read_bytes()).hexdigest()==sys.argv[2]
 cfg=Config()
 stage='dev_target'
 assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 external=uuid.uuid4()
 first_selected=asyncio.Event(); second_selected=asyncio.Event(); release=asyncio.Event()
 tasks=[]; thread_pk=None
 try:
  stage='fixture'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
   other_owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert other_owner is not None and owner!=other_owner
   thread_pk=await db.scalar(text('INSERT INTO profile.chat_threads '
    '(thread_id,user_id,title,created_at,updated_at) '
    'VALUES (:thread,:owner,\'merge acceptance\',now(),now()) '
    'RETURNING id'),{'thread':external,'owner':owner})
   message=await db.scalar(text('INSERT INTO profile.chat_messages '
    '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
    'VALUES (:message,:thread,:owner,\'assistant\',\'synthetic fixture\','
    'CAST(:meta AS JSONB),now()) '
    'RETURNING id'),{'message':uuid.uuid4(),'thread':thread_pk,'owner':owner,
     'meta':json.dumps({'model':'author-model','document_outcome':'deferred','keep':{'a':1}})})
   await db.commit()
  ids={'pdf':uuid.uuid4(),'source_bundle':uuid.uuid4()}
  base={'assistant_message_id':message,'user_id':owner,'thread_id':str(external)}
  class HeldRead:
   def __init__(self,inner,event,hold=False): self.inner=inner; self.event=event; self.hold=hold
   async def execute(self,query,params):
    result=await self.inner.execute(query,params)
    if 'FROM profile.chat_messages' in str(query) and str(query).lstrip().startswith('SELECT'):
     self.event.set()
     if self.hold: await release.wait()
    return result
  stage='concurrent_merge'
  async with connector.get_session_context() as first,connector.get_session_context() as second:
   first_pid=await first.scalar(text('SELECT pg_backend_pid()'))
   second_pid=await second.scalar(text('SELECT pg_backend_pid()'))
   async def deliver(db,event,role,hold=False):
    await service._attach_generated_file(HeldRead(db,event,hold),
     {**base,'role':role,'filename':'document.pdf' if role=='pdf' else 'source.zip',
      'mime_type':'application/pdf' if role=='pdf' else 'application/zip'},ids[role])
    await db.commit()
   tasks.append(asyncio.create_task(deliver(first,first_selected,'pdf',True)))
   await asyncio.wait_for(first_selected.wait(),3)
   tasks.append(asyncio.create_task(deliver(second,second_selected,'source_bundle')))
   blocked=False
   async with connector.get_session_context() as monitor:
    async with asyncio.timeout(3):
     while not second_selected.is_set():
      blocked=bool(await monitor.scalar(text('SELECT :first=ANY(pg_blocking_pids(:second))'),
       {'first':first_pid,'second':second_pid}))
      if blocked: break
      await asyncio.sleep(0.02)
   if second_selected.is_set(): await asyncio.wait_for(tasks[1],3)
   release.set()
   await asyncio.wait_for(asyncio.gather(*tasks),5)
  stage='merge_assertion'
  async with connector.get_session_context() as db:
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':message})
   assert {v['file_id'] for v in metadata['generated_files']}=={str(v) for v in ids.values()}
   assert blocked
   assert metadata['model']=='author-model' and metadata['keep']=={'a':1}
   assert metadata['document_outcome']==metadata['execution_status']=='completed'
   stage='replay'
   await service._attach_generated_file(db,
    {**base,'role':'source_bundle','filename':'source.zip','mime_type':'application/zip'},
    ids['source_bundle'])
   await db.commit()
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':message})
   assert len(metadata['generated_files'])==2
   stage='origin_race'
   origin_uuid=uuid.uuid4()
   async with connector.get_session_context() as later:
    # The origin insert remains uncommitted while a competing turn commits a
    # newer assistant row. Latest-message lookup can now select the wrong turn.
    original=await db.scalar(text('INSERT INTO profile.chat_messages '
     '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
     'VALUES (:mid,:thread,NULL,\'assistant\',\'original\',\'{}\'::jsonb,now()) RETURNING id'),
     {'mid':origin_uuid,'thread':thread_pk})
    newer=await later.scalar(text('INSERT INTO profile.chat_messages '
     '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
     'VALUES (:mid,:thread,NULL,\'assistant\',\'competing\',\'{}\'::jsonb,now()) RETURNING id'),
     {'mid':uuid.uuid4(),'thread':thread_pk})
    await later.commit()
   assert newer>original
   exact={'origin_message_id':str(origin_uuid)}
   descriptor={'build_id':uuid.uuid4().hex,
     'artifact_id':uuid.uuid4().hex,'role':'pdf','source_digest':'a'*64,
     'artifact_sha256':'b'*64,'artifact_size':1,'filename':'fixture.pdf',
     'mime_type':'application/pdf'}
   jobs=await enqueue(db,user_id=owner,thread_id=str(external),workspace_id='opaque',
    billing_job_id=uuid.uuid4().hex,descriptors=(descriptor,),**exact)
   target=await db.scalar(text('SELECT assistant_message_id '
    'FROM profile.document_publication_job WHERE id=:id'),{'id':jobs[0]['id']})
   assert target==original
   replay=await enqueue(db,user_id=owner,thread_id=str(external),workspace_id='opaque',
    billing_job_id=uuid.uuid4().hex,descriptors=(descriptor,),**exact)
   assert replay[0]['id']==jobs[0]['id']
   assert await db.scalar(text('SELECT assistant_message_id '
    'FROM profile.document_publication_job WHERE id=:id'),{'id':replay[0]['id']})==original
   await db.rollback()
   await db.execute(text('DELETE FROM profile.chat_messages WHERE id=:id AND thread_id=:thread'),
    {'id':newer,'thread':thread_pk})
   await db.commit()
   stage='binding_assertion'
   for changes in ({'user_id':other_owner},{'thread_id':str(uuid.uuid4())}):
    await service._attach_generated_file(db,
     {**base,'role':'pdf','filename':'unowned.pdf','mime_type':'application/pdf',**changes},
     uuid.uuid4())
    observed=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
     {'id':message})
    assert observed==metadata
    await db.rollback()
   stage='sender_binding'
   user_message=await db.scalar(text('INSERT INTO profile.chat_messages '
    '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
    'VALUES (:mid,:thread,:owner,\'user\',\'synthetic user\',\'{}\'::jsonb,now()) RETURNING id'),
    {'mid':uuid.uuid4(),'thread':thread_pk,'owner':owner})
   await service._attach_generated_file(db,
    {**base,'assistant_message_id':user_message,'role':'pdf','filename':'unowned.pdf',
     'mime_type':'application/pdf'},uuid.uuid4())
   assert await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':user_message})=={}
   await db.rollback()
   stage='enqueue_binding'
   for candidate,expected_message in ((other_owner,None),(owner,message)):
    jobs=await enqueue(db,user_id=candidate,thread_id=str(external),workspace_id='opaque',
     billing_job_id=uuid.uuid4().hex,descriptors=({'build_id':uuid.uuid4().hex,
      'artifact_id':uuid.uuid4().hex,'role':'pdf','source_digest':'a'*64,
      'artifact_sha256':'b'*64,'artifact_size':1,'filename':'fixture.pdf',
      'mime_type':'application/pdf'},))
    assert len(jobs)==1
    attached=await db.scalar(text('SELECT assistant_message_id '
     'FROM profile.document_publication_job WHERE id=:id'),{'id':jobs[0]['id']})
    assert attached==expected_message
    await db.rollback()
    assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':jobs[0]['id']})==0
   stage='rollback'
   await service._attach_generated_file(db,
    {**base,'role':'source_bundle','filename':'uncommitted.zip','mime_type':'application/zip'},
    uuid.uuid4())
   await db.rollback()
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':message})
   assert len(metadata['generated_files'])==2
  return {'row_lock_observed':True,'both_files_preserved':True,
   'unrelated_metadata_preserved':True,'replay_idempotent':True,'rollback_preserved':True,
   'owner_thread_bound':True,'enqueue_owner_bound':True,'sender_bound':True,'exact_origin':True}
 finally:
  release.set()
  for task in tasks:
   if not task.done(): task.cancel()
  await asyncio.gather(*tasks,return_exceptions=True)
  if thread_pk is not None:
   async with connector.get_session_context() as db:
    await db.execute(text('DELETE FROM profile.chat_threads '
     'WHERE id=:id AND thread_id=:thread AND user_id=:owner'),
     {'id':thread_pk,'thread':external,'owner':owner})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.chat_threads '
     'WHERE thread_id=:thread'),
     {'thread':external})==0
    assert await db.scalar(text('SELECT count(*) FROM profile.chat_messages WHERE id=:id'),
     {'id':message})==0
    cleaned=True
  await connector.close()
try:
 checks=asyncio.run(main())
 print(json.dumps({'status':'passed','checks':checks,'fixture_cleaned':cleaned}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage,'fixture_cleaned':cleaned})); raise SystemExit(1)
"""


def test_concurrent_artifact_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("S37_LIVE_GENERATED_FILES_MERGE") != "1", reason="dev SQL opt-in")
async def test_actual_postgres_pdf_and_zip_deliveries_preserve_both_message_references():
    expected = hashlib.sha256(_MODULE.read_bytes()).hexdigest()
    repository_expected = hashlib.sha256(_REPOSITORY.read_bytes()).hexdigest()
    result = await asyncio.to_thread(
        subprocess.run,
        [
            "docker",
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-",
            expected,
            repository_expected,
        ],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "bounded merge report missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, f"merge failed at {report.get('stage', 'unknown')}"
    assert report == {
        "status": "passed",
        "checks": {
            "row_lock_observed": True,
            "both_files_preserved": True,
            "unrelated_metadata_preserved": True,
            "replay_idempotent": True,
            "rollback_preserved": True,
            "owner_thread_bound": True,
            "enqueue_owner_bound": True,
            "sender_bound": True,
            "exact_origin": True,
        },
        "fixture_cleaned": True,
    }
