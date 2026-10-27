"""Real isolated MinIO + dev SQL across process exit; compiler/audit/WS are synthetic."""

import ast
import hashlib
import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest

_MODULES = (
    "service/services/chat/application/documents/publication/service.py",
    "service/services/chat/application/documents/publication/lease.py",
    "service/services/chat/persistence/documents/publication.py",
    "service/services/files/application/file_saver_service.py",
    "service/infrastructure/storage/minio_file_storage.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,os,sys,threading,time,uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from PyPDF2 import PdfReader
from service.settings import Config,MinioConfig
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.chat.application.documents.publication import service as service
from service.services.chat.application.documents.publication import lease as lease
from service.services.chat.persistence.documents import publication as jobs
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository
from service.models.key_value import ServiceType

values=json.loads(sys.stdin.read()); stage='source_parity'; cleaned=False
def pdf_fixture():
 # Minimal valid test PDF, not a compiler/visual/profile acceptance fixture.
 content=b'BT /F1 12 Tf 72 720 Td (storage recovery fixture) Tj ET\n'
 objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
  b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
   b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
  b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'endstream']
 body=b'%PDF-1.4\n'+b'% storage boundary padding\n'*80000; offsets=[0]
 for number,obj in enumerate(objects,1):
  offsets.append(len(body)); body+=str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
 xref=len(body); body+=b'xref\n0 6\n0000000000 65535 f \n'
 for offset in offsets[1:]: body+=f'{offset:010d} 00000 n \n'.encode()
 body+=b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'
 assert PdfReader(BytesIO(body)).pages[0].extract_text().strip()=='storage recovery fixture'
 return body

async def main():
 global stage,cleaned
 modules=(service.__file__,lease.__file__,jobs.__file__,
  sys.modules[FileSaverService.__module__].__file__,sys.modules[MinioFileStorage.__module__].__file__)
 assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected
  for path,expected in zip(modules,values['digests'],strict=True))
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True); identity=values['identity']
 external=uuid.UUID(identity); owner=None; storage=None
 try:
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
  if values['mode']=='cleanup':
   stage='cleanup'
   async with connector.get_session_context() as db:
    rows=(await db.execute(text('SELECT * FROM profile.document_publication_job '
     'WHERE user_id=:owner AND billing_job_id=:marker AND thread_id=:thread'),
     {'owner':owner,'marker':identity,'thread':str(external)})).mappings().all()
    intents=[jobs.upload_intent(dict(row)) for row in rows]
    await db.execute(text('DELETE FROM profile.document_publication_job '
     'WHERE user_id=:owner AND billing_job_id=:marker AND thread_id=:thread'),
     {'owner':owner,'marker':identity,'thread':str(external)})
    if intents:
     await db.execute(text('DELETE FROM profile.user_file '
      'WHERE user_id=:owner AND upload_intent_id=ANY(:intents)'),{'owner':owner,'intents':intents})
    await db.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:thread '
     'AND user_id=:owner'),{'thread':external,'owner':owner})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE user_id=:owner AND billing_job_id=:marker'),{'owner':owner,'marker':identity})==0
    assert await db.scalar(text('SELECT count(*) FROM profile.chat_threads '
     'WHERE user_id=:owner AND thread_id=:thread'),{'owner':owner,'thread':external})==0
    if intents:
     assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
      'WHERE user_id=:owner AND upload_intent_id=ANY(:intents)'),
      {'owner':owner,'intents':intents})==0
   cleaned=True; return {'status':'cleaned','fixture_cleaned':True}

  stage='isolated_storage'
  storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
   endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
   bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
   retry_attempts=1,retry_backoff=0,presign_expiry=60))
  files=FileSaverService(FileRepository(connector),'acceptance/'+identity,storage)
  body=pdf_fixture(); digest=hashlib.sha256(body).hexdigest()
  async def chunks():
   for offset in range(0,len(body),65536): yield body[offset:offset+65536]
  async def read_job(db,artifact):
   return dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
    'WHERE user_id=:owner AND billing_job_id=:marker AND artifact_id=:artifact '
    'AND thread_id=:thread'),{'owner':owner,'marker':identity,'artifact':artifact,
     'thread':str(external)})).mappings().one())

  if values['mode']=='exit':
   stage='fixture'
   async with connector.get_session_context() as db:
    thread_pk=await db.scalar(text('INSERT INTO profile.chat_threads '
     '(thread_id,user_id,title,created_at,updated_at) '
     'VALUES (:thread,:owner,\'storage process acceptance\',now(),now()) RETURNING id'),
     {'thread':external,'owner':owner})
    await db.execute(text('INSERT INTO profile.chat_messages '
     '(message_id,thread_id,user_id,sender,content,metadata,created_at) '
     'VALUES (:message,:thread,:owner,\'assistant\',\'synthetic fixture\','
     'CAST(:metadata AS JSONB),now())'),
     {'message':uuid.uuid4(),'thread':thread_pk,'owner':owner,
      'metadata':json.dumps({'document_outcome':'deferred','keep':1})})
    for artifact in ('saved','revoked','cancelled','failed'):
     created=await jobs.enqueue(db,user_id=owner,thread_id=str(external),workspace_id=identity,
      billing_job_id=identity,descriptors=({'build_id':identity,'artifact_id':artifact,
       'role':'pdf','source_digest':'b'*64,'artifact_sha256':digest,'artifact_size':len(body),
       'filename':'boundary.pdf','mime_type':'application/pdf'},))
     await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
      "lease_expires_at=clock_timestamp()+interval '600 seconds',"
      "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
      {'token':uuid.uuid4(),'id':created[0]['id'],'owner':owner})
    await db.commit()
   download=SimpleNamespace(chunks=chunks,close=AsyncMock())
   class ExitAfterSave:
    async def save_stream(self,*args,**kwargs):
     saved=await files.save_stream(*args,**kwargs)
     assert not saved.reused
     print(json.dumps({'status':'saved_before_exit'}),flush=True)
     os._exit(73)  # Only this docker-exec child exits, never a shared worker.
   with (
    patch.object(service,'read_binding',AsyncMock(return_value={'workspace_id':identity})),
    patch.object(service,'_agent_ref',lambda *_:{}),
    patch.object(service,'_ensure_audited_durable',AsyncMock(return_value='ready')),
    patch.object(service,'document_build_status',AsyncMock(return_value={
     'build_id':identity,'source_digest':'b'*64,'state':'ready','artifacts':[
     {'artifact_id':'saved','sha256':digest,'size':len(body),'mime_type':'application/pdf'}]})),
    patch.object(service,'stream_document_artifact',AsyncMock(return_value=download)),
   ):
    stage='save_then_exit'
    async with connector.get_session_context() as db:
     await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=ExitAfterSave(),session=db,row=await read_job(db,'saved'))
   raise AssertionError('process_exit_missing')

  stage='recovery'
  binding=AsyncMock(side_effect=AssertionError('source_must_not_be_replayed'))
  audit=AsyncMock(side_effect=AssertionError('audit_must_not_be_replayed'))
  notify=AsyncMock()
  async with connector.get_session_context() as db:
   row=await read_job(db,'saved'); intent=jobs.upload_intent(row)
   existing=(await db.execute(text('SELECT id,file_name,content_sha256 FROM profile.user_file '
    'WHERE user_id=:owner AND upload_intent_id=:intent'),
    {'owner':owner,'intent':intent})).mappings().one()
   assert row['status']=='pending_delivery' and row['user_file_id'] is None
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages '
    'WHERE id=:id'),{'id':row['assistant_message_id']})
   assert not metadata.get('generated_files')
   await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
    "lease_expires_at=clock_timestamp()+interval '600 seconds' WHERE id=:id AND user_id=:owner"),
    {'token':uuid.uuid4(),'id':row['id'],'owner':owner}); await db.commit()
  with (
   patch.object(service,'read_binding',binding),
   patch.object(service,'_ensure_audited_durable',audit),
   patch('service.services.chat.application.workspace_event_projection.'
    'publish_workspace_invalidation',notify),
   patch.object(files,'save_stream',
    AsyncMock(side_effect=AssertionError('upload_repeated'))) as save,
  ):
   for turn in range(2):
    stage='first_recovery' if turn==0 else 'completed_replay'
    async with connector.get_session_context() as db:
     assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=files,session=db,row=await read_job(db,'saved'))=='delivered'
   binding.assert_not_awaited(); audit.assert_not_awaited(); save.assert_not_awaited()
   assert notify.await_count==1

  stage='lease_loss_after_upload'
  async with connector.get_session_context() as db: revoked=await read_job(db,'revoked')
  lost=asyncio.Event(); calls=0
  async def before_persist():
   nonlocal calls
   calls+=1
   if calls==2:
    async with connector.get_session_context() as db:
     changed=await db.execute(text('UPDATE profile.document_publication_job SET lease_token=:new '
      'WHERE id=:id AND user_id=:owner AND lease_token=:old'),
      {'new':uuid.uuid4(),'id':revoked['id'],'owner':owner,'old':revoked['lease_token']})
     assert changed.rowcount==1; await db.commit()
   await lease.require_publication_lease(connector,revoked,lost)
  try:
   await files.save_stream(owner,ServiceType.CHAT,'boundary.pdf',chunks(),expected_size=len(body),
    expected_sha256=digest,upload_intent_id=jobs.upload_intent(revoked),before_persist=before_persist)
  except lease.PublicationLeaseLost: pass
  else: raise AssertionError('stale_file_persisted')
  assert calls==2
  async with connector.get_session_context() as db:
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner '
    'AND upload_intent_id=ANY(:intents)'),
    {'owner':owner,'intents':[intent,jobs.upload_intent(revoked)]})==1
   delivered=await read_job(db,'saved')
   assert delivered['status']=='delivered' and delivered['user_file_id']==existing['id']
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':row['assistant_message_id']})
   assert len(metadata['generated_files'])==1
   assert metadata['generated_files'][0]['file_id']==str(existing['id']) and metadata['keep']==1

  stage='download_integrity'
  owned=await files.fetch_file_metadata(owner,existing['id'])
  response=await asyncio.to_thread(storage._client.get_object,storage._bucket,owned.file_key)
  received=hashlib.sha256(); size=0
  try:
   for chunk in response.stream(65536): received.update(chunk); size+=len(chunk)
  finally: response.close(); response.release_conn()
  assert size==len(body) and received.hexdigest()==digest
  assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==1

  stage='cancelled_delivery'
  async with connector.get_session_context() as db: cancelled=await read_job(db,'cancelled')
  started,release,committed=threading.Event(),threading.Event(),threading.Event()
  observed=[]; real_put=storage._client.put_object
  def held_put(**kwargs):
   observed.append(kwargs['data']); started.set()
   if not release.wait(10): raise TimeoutError('fixture release missing')
   real_put(**kwargs); committed.set()
  cancelled_status={'build_id':identity,'source_digest':'b'*64,'state':'ready','artifacts':[
   {'artifact_id':'cancelled','sha256':digest,'size':len(body),'mime_type':'application/pdf'}]}
  cancelled_download=SimpleNamespace(chunks=chunks,close=AsyncMock())
  async def deliver_cancelled():
   async with connector.get_session_context() as db:
    return await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
     file_service=files,session=db,row=await read_job(db,'cancelled'))
  with (
   patch.object(service,'read_binding',AsyncMock(return_value={'workspace_id':identity})),
   patch.object(service,'_agent_ref',lambda *_:{}),
   patch.object(service,'_ensure_audited_durable',AsyncMock(return_value='ready')),
   patch.object(service,'document_build_status',AsyncMock(return_value=cancelled_status)),
   patch.object(service,'stream_document_artifact',AsyncMock(return_value=cancelled_download)),
   patch('service.services.chat.application.workspace_event_projection.'
    'publish_workspace_invalidation',AsyncMock()) as cancelled_notify,
  ):
   with patch.object(storage._client,'put_object',side_effect=held_put) as put:
    task=asyncio.create_task(deliver_cancelled())
    try:
     assert await asyncio.to_thread(started.wait,3)
     task.cancel(); await asyncio.sleep(0); await asyncio.sleep(0)
     assert not task.done() and not observed[0].closed
     release.set()
     try: await asyncio.wait_for(task,20)
     except asyncio.CancelledError: pass
     else: raise AssertionError('delivery cancellation lost')
     assert committed.is_set() and observed[0].closed and put.call_count==1
    finally:
     release.set(); await asyncio.gather(task,return_exceptions=True)
   cancelled_download.close.assert_awaited_once(); cancelled_notify.assert_not_awaited()
   async with connector.get_session_context() as db:
    unchanged=await read_job(db,'cancelled')
    assert unchanged['status']=='pending_delivery' and unchanged['user_file_id'] is None
    assert unchanged['lease_token']==cancelled['lease_token'] and unchanged['attempts']==0
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner '
     'AND upload_intent_id=:intent'),
     {'owner':owner,'intent':jobs.upload_intent(cancelled)})==0
    assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==1
    # Expire/reclaim only this owned fixture, not the global production claim queue.
    await db.execute(text("UPDATE profile.document_publication_job SET "
     "lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id AND user_id=:owner"),
     {'id':cancelled['id'],'owner':owner})
    reclaimed=await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:new,"
     "lease_expires_at=clock_timestamp()+interval '600 seconds' "
     "WHERE id=:id AND user_id=:owner AND lease_token=:old "
     "AND lease_expires_at<clock_timestamp()"),
     {'id':cancelled['id'],'owner':owner,'old':cancelled['lease_token'],'new':uuid.uuid4()})
    assert reclaimed.rowcount==1; await db.commit()
   stage='cancelled_recovery'
   async with connector.get_session_context() as db:
    assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
     file_service=files,session=db,row=cancelled)=='deferred'
   assert service.stream_document_artifact.await_count==1
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==1
   for turn in range(2): assert await deliver_cancelled()=='delivered'
   assert cancelled_notify.await_count==1 and cancelled_download.close.await_count==2
   async with connector.get_session_context() as db:
    delivered_cancel=await read_job(db,'cancelled')
    assert delivered_cancel['status']=='delivered' and delivered_cancel['user_file_id'] is not None
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner '
     'AND upload_intent_id=:intent'),
     {'owner':owner,'intent':jobs.upload_intent(cancelled)})==1
    metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
     {'id':cancelled['assistant_message_id']})
    ids=[entry['file_id'] for entry in metadata['generated_files']]
    assert len(ids)==2 and len(set(ids))==2 and str(delivered_cancel['user_file_id']) in ids
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==2
   stage='cancelled_download_integrity'
   final_file=await files.fetch_file_metadata(owner,delivered_cancel['user_file_id'])
   response=await asyncio.to_thread(storage._client.get_object,storage._bucket,final_file.file_key)
   received=hashlib.sha256(); size=0
   try:
    for chunk in response.stream(65536): received.update(chunk); size+=len(chunk)
   finally: response.close(); response.release_conn()
   assert size==len(body) and received.hexdigest()==digest

  stage='failed_upload_delivery'
  failed_status={'build_id':identity,'source_digest':'b'*64,'state':'ready','artifacts':[
   {'artifact_id':'failed','sha256':digest,'size':len(body),'mime_type':'application/pdf'}]}
  failed_download=SimpleNamespace(chunks=chunks,close=AsyncMock())
  def committed_but_failed(**kwargs):
   real_put(**kwargs)
   assert storage._client.stat_object(storage._bucket,kwargs['object_name']).size==len(body)
   raise OSError('PRIVATE_FAILED_UPLOAD_BODY')
  with (
   patch.object(service,'read_binding',AsyncMock(return_value={'workspace_id':identity})),
   patch.object(service,'_agent_ref',lambda *_:{}),
   patch.object(service,'_ensure_audited_durable',AsyncMock(return_value='ready')),
   patch.object(service,'document_build_status',AsyncMock(return_value=failed_status)),
   patch.object(service,'stream_document_artifact',AsyncMock(return_value=failed_download)),
   patch('service.services.chat.application.workspace_event_projection.'
    'publish_workspace_invalidation',AsyncMock()) as failed_notify,
  ):
   with patch.object(storage._client,'put_object',side_effect=committed_but_failed) as put:
    async with connector.get_session_context() as db:
     failed=await read_job(db,'failed')
     assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=files,session=db,row=failed)=='deferred'
     put.assert_called_once()  # This isolated storage is configured for one SDK attempt.
     deferred=await read_job(db,'failed')
     assert deferred['status']=='pending_delivery' and deferred['lease_token'] is None
     assert deferred['failure_code']=='unavailable' and deferred['attempts']==1
     assert deferred['user_file_id'] is None
     assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner '
      'AND upload_intent_id=:intent'),
      {'owner':owner,'intent':jobs.upload_intent(failed)})==0
     # Keep this fault fixture out of the shared scheduler before committing defer.
     await db.execute(text("UPDATE profile.document_publication_job SET "
      "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
      {'id':failed['id'],'owner':owner}); await db.commit()
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==2
   failed_notify.assert_not_awaited(); failed_download.close.assert_awaited_once()
   stage='failed_upload_recovery'
   async with connector.get_session_context() as db:
    claimed=await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:new,"
     "lease_expires_at=clock_timestamp()+interval '600 seconds' "
     "WHERE id=:id AND user_id=:owner AND lease_token IS NULL AND status='pending_delivery'"),
     {'id':failed['id'],'owner':owner,'new':uuid.uuid4()})
    assert claimed.rowcount==1; await db.commit()
   for turn in range(2):
    async with connector.get_session_context() as db:
     assert await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
      file_service=files,session=db,row=await read_job(db,'failed'))=='delivered'
   assert failed_notify.await_count==1 and failed_download.close.await_count==2
   async with connector.get_session_context() as db:
    finished=await read_job(db,'failed')
    assert finished['status']=='delivered' and finished['attempts']==1
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner '
     'AND upload_intent_id=:intent'),
     {'owner':owner,'intent':jobs.upload_intent(failed)})==1
    metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
     {'id':failed['assistant_message_id']})
    ids=[entry['file_id'] for entry in metadata['generated_files']]
    assert len(ids)==3 and len(set(ids))==3 and str(finished['user_file_id']) in ids
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==3
   stage='failed_upload_download_integrity'
   final_file=await files.fetch_file_metadata(owner,finished['user_file_id'])
   response=await asyncio.to_thread(storage._client.get_object,storage._bucket,final_file.file_key)
   received=hashlib.sha256(); size=0
   try:
    for chunk in response.stream(65536): received.update(chunk); size+=len(chunk)
   finally: response.close(); response.release_conn()
   assert size==len(body) and received.hexdigest()==digest
  return {'status':'passed','process_recovery':True,'one_file_one_object':True,
   'lease_compensation':True,'download_integrity':True,'cancelled_outbox_recovery':True,
   'cancelled_metadata_writes':0,'recovered_files':3,'cancelled_stale_holder_blocked':True,
   'failed_upload_compensation':True,'failed_upload_recovery':True}
 finally:
  if storage is not None: storage._client._http.clear()
  await connector.close()
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage,'fixture_cleaned':cleaned})); raise SystemExit(1)
"""


def _docker(*args, env=None, input=None, timeout=30):
    return subprocess.run(
        ["docker", *args], env=env, input=input, capture_output=True, timeout=timeout, check=False
    )


def _checked(*args, **kwargs):
    result = _docker(*args, **kwargs)
    if result.returncode:
        raise RuntimeError("isolated_document_storage_docker")
    return result.stdout.decode().strip()


def _report(result):
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "bounded storage process report missing"
    return json.loads(lines[-1])


def test_storage_process_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_STORAGE_PROCESS_RECOVERY") != "1", reason="isolated MinIO + dev SQL"
)
def test_real_storage_commit_survives_process_exit_and_stale_upload_is_compensated():
    identity = uuid.uuid4().hex
    name = f"gpthub-s37-delivery-{identity}"
    created = False
    environment = dict(os.environ)
    environment["MINIO_ROOT_USER"] = "s37" + identity
    environment["MINIO_ROOT_PASSWORD"] = secrets.token_hex(24)
    values = {
        "identity": identity,
        "endpoint": f"{name}:9000",
        "access_key": environment["MINIO_ROOT_USER"],
        "secret_key": environment["MINIO_ROOT_PASSWORD"],
        "digests": [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES],
    }

    def probe(mode):
        return _docker(
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            _PROBE,
            input=json.dumps({**values, "mode": mode}).encode(),
            timeout=45,
        )

    try:
        networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-backend-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        database_networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-postgres-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        shared = sorted(set(networks) & set(database_networks))
        assert len(shared) == 1, "dev network must be unambiguous"
        image = _checked("inspect", "gpthub-dev-minio-1", "--format", "{{.Image}}")
        assert image.startswith("sha256:")
        _checked(
            "create",
            "--name",
            name,
            "--label",
            f"gpthub.s37.delivery={identity}",
            "--network",
            shared[0],
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            image,
            "server",
            "/data",
            env=environment,
        )
        created = True
        _checked("start", name)
        health = (
            "import sys,time,urllib.request\n"
            "for attempt in range(30):\n"
            " try:\n"
            "  response=urllib.request.urlopen(sys.argv[1],timeout=1)\n"
            "  ok=response.status==200; response.close()\n"
            "  if ok: sys.exit(0)\n"
            " except Exception: pass\n"
            " time.sleep(0.5)\n"
            "sys.exit(1)"
        )
        _checked(
            "exec",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            health,
            f"http://{name}:9000/minio/health/ready",
        )
        first = probe("exit")
        assert first.returncode == 73 and _report(first) == {"status": "saved_before_exit"}
        recovered = probe("recover")
        report = _report(recovered)
        assert recovered.returncode == 0, (
            f"storage proof failed at {report.get('stage', 'unknown')}"
        )
        assert report == {
            "status": "passed",
            "process_recovery": True,
            "one_file_one_object": True,
            "lease_compensation": True,
            "download_integrity": True,
            "cancelled_outbox_recovery": True,
            "cancelled_metadata_writes": 0,
            "recovered_files": 3,
            "cancelled_stale_holder_blocked": True,
            "failed_upload_compensation": True,
            "failed_upload_recovery": True,
        }
    finally:
        try:
            cleanup = probe("cleanup")
            cleaned = cleanup.returncode == 0 and _report(cleanup) == {
                "status": "cleaned",
                "fixture_cleaned": True,
            }
        finally:
            if created:
                actual = _checked(
                    "inspect", name, "--format", '{{index .Config.Labels "gpthub.s37.delivery"}}'
                )
                assert actual == identity
                _checked("rm", "--force", "--volumes", name)
        assert cleaned, "owned SQL fixture cleanup not confirmed"
