"""Actual disposable MinIO stop/start plus native delivery/SQL; audit/source are fixtures."""

import ast
import concurrent.futures
import json
import os
import subprocess

import pytest

from tests import test_direct_upload_live as isolated
from tests.test_direct_upload_live import _run_minio_probe
from tests.test_document_storage_process_recovery_live import _checked

_MODULES = (
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/application/file_saver_service.py",
    "service/services/files/persistence/file_repository.py",
    "service/services/chat/application/documents/publication/service.py",
    "service/services/chat/application/documents/publication/lease.py",
    "service/services/chat/persistence/documents/publication.py",
    "service/services/chat/persistence/documents/audit/attempts.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,time,uuid
from pathlib import Path
from unittest.mock import AsyncMock,patch
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config,MinioConfig
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository
from service.services.chat.application.documents.publication import service as service
from service.services.chat.application.documents.publication import lease as lease
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.persistence.documents.audit import attempts as audits
values=json.loads(sys.stdin.readline()); identity=values['identity']; stage='source_parity'
external=uuid.uuid5(uuid.UUID(identity),'outage-thread'); publication=None; owner=None
storage=None; connector=None; files=None; created=False; cleaned=False
body=b'%PDF-fixture-storage-only\n'+b'streamed-outage-fixture\n'*80000
digest=hashlib.sha256(body).hexdigest()
source='b'*64; artifact='outage-pdf'
async def row(db):
 return dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
  'WHERE id=:id AND user_id=:owner AND thread_id=:thread AND billing_job_id=:marker'),
  {'id':publication,'owner':owner,'thread':str(external),'marker':identity})).mappings().one())
async def cleanup_fixture():
 global cleaned
 if connector is None or owner is None: return
 async with connector.get_session_context() as db:
  records=(await db.execute(text('SELECT j.* FROM profile.document_publication_job j '
   'WHERE user_id=:owner AND thread_id=:thread AND billing_job_id=:marker'),
   {'owner':owner,'thread':str(external),'marker':identity})).mappings().all()
  intents=[jobs.upload_intent(dict(item)) for item in records]
  for intent in intents:
   metadata=await files.repository.fetch_user_file_by_upload_intent(owner,intent)
   if metadata is not None:
    assert metadata.file_name.startswith('outage/'+identity+'/')
    await files.delete(owner,metadata.id)
  await db.execute(text('DELETE FROM profile.document_publication_job '
   'WHERE user_id=:owner AND thread_id=:thread AND billing_job_id=:marker'),
   {'owner':owner,'thread':str(external),'marker':identity})
  await db.execute(text('DELETE FROM profile.chat_threads WHERE user_id=:owner '
   'AND thread_id=:thread'),{'owner':owner,'thread':external})
  await db.commit()
  assert await db.scalar(text('SELECT count(*) FROM profile.chat_threads '
   'WHERE user_id=:owner AND thread_id=:thread'),{'owner':owner,'thread':external})==0
  assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
   'WHERE user_id=:owner AND billing_job_id=:marker'),{'owner':owner,'marker':identity})==0
  if intents:
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
    'WHERE user_id=:owner AND upload_intent_id=ANY(:intents)'),
    {'owner':owner,'intents':intents})==0
 if storage is not None:
  for item in storage._client.list_objects(storage._bucket,recursive=True):
   assert item.object_name.startswith('outage/'+identity+'/')
   await storage.delete_file(file_key=item.object_name)
  assert not list(storage._client.list_objects(storage._bucket,recursive=True))
 cleaned=True
async def main():
 global connector,storage,files,owner,publication,created,stage
 modules=(sys.modules[MinioFileStorage.__module__],sys.modules[FileSaverService.__module__],
  sys.modules[FileRepository.__module__],service,lease,jobs,audits)
 for module,expected in zip(modules,values['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
  endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
  bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
  retry_attempts=1,retry_backoff=0,presign_expiry=60))
 files=FileSaverService(FileRepository(connector),'outage/'+identity,storage)
 async with connector.get_session_context() as db:
  owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
   {'email':'s38-video-acceptance@example.com'})
  assert owner is not None
  if values.get('mode')=='cleanup': return {'status':'cleanup'}
  stage='fixture_create'
  thread_pk=await db.scalar(text('INSERT INTO profile.chat_threads '
   '(thread_id,user_id,title,created_at,updated_at) VALUES '
   '(:thread,:owner,\'isolated outage acceptance\',now(),now()) RETURNING id'),
   {'thread':external,'owner':owner})
  await db.execute(text('INSERT INTO profile.chat_messages '
   '(message_id,thread_id,user_id,sender,content,metadata,created_at) VALUES '
   '(:message,:thread,:owner,\'assistant\',\'synthetic outage fixture\','
   'CAST(:metadata AS JSONB),now())'),{'message':uuid.uuid4(),'thread':thread_pk,
    'owner':owner,'metadata':json.dumps({'document_outcome':'deferred','keep':1})})
  descriptor={'build_id':identity,'artifact_id':artifact,'role':'pdf','source_digest':source,
   'artifact_sha256':digest,'artifact_size':len(body),'filename':'outage.pdf',
   'mime_type':'application/pdf'}
  queued=await jobs.enqueue(db,user_id=owner,thread_id=str(external),workspace_id=identity,
   billing_job_id=identity,descriptors=(descriptor,),initial_status='pending_delivery')
  publication=queued[0]['id']
  await db.execute(text('UPDATE profile.document_publication_job SET lease_token=:lease, '
   "lease_expires_at=clock_timestamp()+interval '600 seconds', "
   "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
   {'lease':uuid.uuid4(),'id':publication,'owner':owner})
  await db.commit(); created=True
 binding={'workspace_id':identity,'token':'fixture-private','expires_at':time.time()+3600}
 build={'build_id':identity,'source_digest':source,'state':'ready','artifacts':[
  {'artifact_id':artifact,'sha256':digest,'size':len(body),'mime_type':'application/pdf'}]}
 downloads=[]
 class Download:
  def __init__(self): self.closed=False
  async def chunks(self):
   for offset in range(0,len(body),65536): yield body[offset:offset+65536]
  async def close(self): self.closed=True
 async def download(*args,**kwargs):
  item=Download(); downloads.append(item); return item
 notify=AsyncMock()
 async def deliver(db):
  return await service.deliver_one(config=cfg,pg_connector=connector,redis=object(),
   file_service=files,session=db,row=await row(db))
 with (
  patch.object(service,'read_binding',AsyncMock(return_value=binding)),
  patch.object(service,'_ensure_audited_durable',AsyncMock(return_value='ready')),
  patch.object(service,'document_build_status',AsyncMock(return_value=build)),
  patch.object(service,'stream_document_artifact',download),
  patch('service.services.chat.application.workspace_event_projection.'
   'publish_workspace_invalidation',notify),
 ):
  stage='await_offline'; print(json.dumps({'phase':'prepared'}),flush=True)
  assert sys.stdin.readline().strip()=='offline'
  stage='offline_delivery'
  async with connector.get_session_context() as db:
   assert await deliver(db)=='deferred'
   deferred=await row(db)
   assert deferred['status']=='pending_delivery' and deferred['lease_token'] is None
   assert deferred['failure_code']=='unavailable' and deferred['attempts']==1
   assert deferred['user_file_id'] is None
   intent=jobs.upload_intent(deferred)
   assert await files.repository.fetch_user_file_by_upload_intent(owner,intent) is None
   metadata=await db.scalar(text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':deferred['assistant_message_id']})
   assert not metadata.get('generated_files') and notify.await_count==0
   # Keep this exact fault row invisible to the shared scheduler after defer.
   await db.execute(text("UPDATE profile.document_publication_job SET "
    "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
    {'id':publication,'owner':owner}); await db.commit()
  assert len(downloads)==1 and downloads[0].closed
  stage='await_online'; print(json.dumps({'phase':'deferred'}),flush=True)
  assert sys.stdin.readline().strip()=='online'
  stage='recovery_delivery'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.document_publication_job SET lease_token=:lease, '
    "lease_expires_at=clock_timestamp()+interval '600 seconds' "
    'WHERE id=:id AND user_id=:owner AND status=\'pending_delivery\''),
    {'lease':uuid.uuid4(),'id':publication,'owner':owner}); await db.commit()
   assert await deliver(db)=='delivered'
  async with connector.get_session_context() as db:
   delivered=await row(db); metadata=await db.scalar(
    text('SELECT metadata FROM profile.chat_messages WHERE id=:id'),
    {'id':delivered['assistant_message_id']})
   assert delivered['status']=='delivered' and delivered['user_file_id']
   assert metadata['keep']==1 and len(metadata['generated_files'])==1
   assert metadata['generated_files'][0]['file_id']==str(delivered['user_file_id'])
   assert 'url' not in metadata['generated_files'][0]
   file=await files.repository.fetch_user_file_by_upload_intent(owner,intent)
   assert file.id==delivered['user_file_id'] and file.content_sha256==digest
   assert len(downloads)==2 and all(item.closed for item in downloads)
   assert notify.await_count==1
   stage='completed_replay'; assert await deliver(db)=='delivered'
   assert len(downloads)==2 and notify.await_count==1
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
    'WHERE user_id=:owner AND upload_intent_id=:intent'),{'owner':owner,'intent':intent})==1
   assert await db.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
    'WHERE publication_job_id=:id'),{'id':publication})==0
  response=await asyncio.to_thread(storage._client.get_object,storage._bucket,file.file_name)
  try:
   actual=hashlib.sha256(); size=0
   for chunk in response.stream(65536): actual.update(chunk); size+=len(chunk)
   assert size==len(body) and actual.hexdigest()==digest
  finally: response.close(); response.release_conn()
 return {'status':'passed','outage_deferred':True,'no_phantom_file':True,
  'recovered_once':True,'replay_reused':True,'download_hash_verified':True}
async def run():
 global stage
 report=None
 try: report=await main()
 except BaseException: report={'status':'failed','stage':stage}
 finally:
  try: await cleanup_fixture()
  except BaseException: report={'status':'failed','stage':'fixture_cleanup'}
  if storage is not None: storage._client._http.clear()
  if connector is not None: await connector.close()
 report['fixture_cleaned']=cleaned
 return report
report=asyncio.run(run()); print(json.dumps(report),flush=True)
if report['status'] not in {'passed','cleanup'}: raise SystemExit(1)
"""


def _execute_outage(name, values, probe, timeout):
    """Handshake only with this runner's label-owned container; never shared MinIO."""
    assert name == "gpthub-s37-direct-" + values["identity"]
    process = subprocess.Popen(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", probe],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    readers = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    stopped = False

    def frame():
        line = readers.submit(process.stdout.readline).result(timeout=45)
        return json.loads(line)

    def send(payload):
        process.stdin.write(payload.encode() + b"\n")
        process.stdin.flush()

    def owned():
        actual = _checked(
            "inspect", name, "--format", '{{index .Config.Labels "gpthub.s37.direct"}}'
        )
        assert actual == values["identity"], "outage_container_owner_mismatch"

    try:
        send(json.dumps(values))
        assert frame() == {"phase": "prepared"}
        owned()
        _checked("stop", "--time", "2", name)
        stopped = True
        send("offline")
        assert frame() == {"phase": "deferred"}
        owned()
        _checked("start", name)
        stopped = False
        health = (
            "import sys,time,urllib.request\n"
            "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
            "for _ in range(30):\n"
            " try:\n"
            "  response=opener.open(sys.argv[1],timeout=1); response.close(); sys.exit(0)\n"
            " except Exception: time.sleep(.5)\n"
            "sys.exit(1)"
        )
        _checked(
            "exec",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            health,
            "http://" + values["endpoint"] + "/minio/health/ready",
        )
        send("online")
        report = frame()
        process.wait(timeout=20)
        return subprocess.CompletedProcess(
            ["isolated-outbox-outage"], process.returncode, json.dumps(report).encode(), b""
        )
    finally:
        if stopped:
            owned()
            _checked("start", name)
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        readers.shutdown(wait=False, cancel_futures=True)
        if process.stdout:
            process.stdout.close()


def test_outage_probe_compiles_without_running():
    ast.parse(_PROBE)


@pytest.mark.parametrize("fails", [False, True])
def test_handshake_executor_keeps_owned_container_cleanup(monkeypatch, fails):
    identity = "a" * 32
    calls = []

    class Identity:
        hex = identity

    def checked(*args, **kwargs):
        calls.append(args)
        if args[0] == "inspect":
            if "Networks" in args[-1]:
                return json.dumps({"isolated-network": {}})
            if args[-1] == "{{.Image}}":
                return "sha256:fixture"
            return identity
        return ""

    def executor(name, values, probe, timeout):
        assert name == "gpthub-s37-direct-" + identity
        assert values["identity"] == identity and timeout == 240
        assert probe == _PROBE
        if fails:
            raise RuntimeError("bounded_fixture_failure")
        return subprocess.CompletedProcess([], 0, b'{"status":"passed"}', b"")

    monkeypatch.setattr(isolated.uuid, "uuid4", Identity)
    monkeypatch.setattr(isolated, "_checked", checked)
    kwargs = dict(
        real_persistence=True,
        probe=_PROBE,
        modules=_MODULES,
        probe_timeout=240,
        probe_executor=executor,
        expected_report={"status": "passed"},
    )
    if fails:
        with pytest.raises(RuntimeError, match="bounded_fixture_failure"):
            _run_minio_probe(**kwargs)
    else:
        _run_minio_probe(**kwargs)
    assert calls[-1] == ("rm", "--force", "--volumes", "gpthub-s37-direct-" + identity)
    assert all("MINIO_ROOT_PASSWORD=" not in str(args) for args in calls)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_OUTBOX_OUTAGE") != "1", reason="isolated MinIO stop/start/dev SQL"
)
def test_outbox_recovers_after_actual_isolated_minio_stop_start():
    _run_minio_probe(
        real_persistence=True,
        probe=_PROBE,
        modules=_MODULES,
        probe_timeout=240,
        probe_executor=_execute_outage,
        expected_report={
            "status": "passed",
            "outage_deferred": True,
            "no_phantom_file": True,
            "recovered_once": True,
            "replay_reused": True,
            "download_hash_verified": True,
            "fixture_cleaned": True,
        },
    )
