"""Opt-in real MinIO cancellation; SQL, compiler, audit and browser are not covered."""

import ast
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

import pytest

from tests.test_document_storage_process_recovery_live import _checked, _docker, _report

_MODULES = (
    "service/infrastructure/storage/minio_file_storage.py",
    "service/services/files/application/file_saver_service.py",
)

_PROBE = r"""
import asyncio,hashlib,json,logging,sys,threading,uuid
from pathlib import Path
from unittest.mock import AsyncMock,Mock
logging.disable(logging.CRITICAL)
from service.settings import MinioConfig
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService
from service.models.key_value import ServiceType

values=json.loads(sys.stdin.read()); stage='source_parity'
async def main():
 global stage
 for cls,expected in zip((MinioFileStorage,FileSaverService),values['digests'],strict=True):
  actual=hashlib.sha256(Path(sys.modules[cls.__module__].__file__).read_bytes()).hexdigest()
  assert actual==expected
 stage='isolated_storage'
 storage=await asyncio.to_thread(MinioFileStorage,MinioConfig(
  endpoint=values['endpoint'],access_key=values['access_key'],secret_key=values['secret_key'],
  bucket='acceptance',region='us-east-1',secure=False,public_endpoint='',
  retry_attempts=3,retry_backoff=0,presign_expiry=60))
 repository=Mock(fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
  add_file_metadata=AsyncMock())
 saver=FileSaverService(repository,'cancellation/'+values['identity'],storage)
 owner=uuid.uuid4(); body=b'stream boundary fixture\n'*100000
 digest=hashlib.sha256(body).hexdigest(); real_put=storage._client.put_object
 async def chunks():
  for offset in range(0,len(body),65536): yield body[offset:offset+65536]
 async def upload(mode):
  if mode=='bytes': return await saver.save(owner,ServiceType.CHAT,'notes.md',body)
  return await saver.save_stream(owner,ServiceType.CHAT,'notes.md',chunks(),
   expected_size=len(body),expected_sha256=digest,upload_intent_id=uuid.uuid4())
 try:
  for mode,late_failure in (('stream',False),('stream',True),('bytes',False),('bytes',True)):
   stage=mode+('_late_failure' if late_failure else '_late_success')
   started,release,committed=threading.Event(),threading.Event(),threading.Event()
   observed=[]
   def held_put(**kwargs):
    observed.append(kwargs['data']); started.set()
    if not release.wait(10): raise TimeoutError('fixture release missing')
    real_put(**kwargs)
    assert storage._client.stat_object(storage._bucket,kwargs['object_name']).size==len(body)
    committed.set()
    if late_failure: raise OSError('PRIVATE_LATE_STORAGE_BODY')
   storage._client.put_object=Mock(side_effect=held_put)
   task=asyncio.create_task(upload(mode))
   try:
    assert await asyncio.to_thread(started.wait,3)
    task.cancel(); await asyncio.sleep(0); await asyncio.sleep(0)
    assert not task.done() and not observed[0].closed
    task.cancel(); await asyncio.sleep(0)
    assert not task.done() and not observed[0].closed
    release.set()
    try: await asyncio.wait_for(task,20)
    except asyncio.CancelledError: pass
    else: raise AssertionError('cancellation lost')
    assert committed.is_set() and observed[0].closed
    assert storage._client.put_object.call_count==1
    repository.add_file_metadata.assert_not_awaited()
    assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==0
   finally:
    release.set(); await asyncio.gather(task,return_exceptions=True)
  for mode in ('stream','bytes'):
   stage=mode+'_exhausted_upload'
   def failed_put(**kwargs):
    real_put(**kwargs)
    raise OSError('PRIVATE_EXHAUSTED_UPLOAD_BODY')
   storage._client.put_object=Mock(side_effect=failed_put)
   try: await upload(mode)
   except OSError: pass
   else: raise AssertionError('upload failure lost')
   assert storage._client.put_object.call_count==3
   repository.add_file_metadata.assert_not_awaited()
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==0
  stage='subsequent_success'
  storage._client.put_object=real_put
  async def metadata(row):
   row.id=uuid.uuid4(); return row
  repository.add_file_metadata.side_effect=metadata
  for mode in ('stream','bytes'):
   saved=await upload(mode)
   response=await asyncio.to_thread(storage._client.get_object,storage._bucket,saved.file_key)
   try:
    received=hashlib.sha256(); size=0
    for chunk in response.stream(65536): received.update(chunk); size+=len(chunk)
    assert size==len(body) and received.hexdigest()==digest
   finally: response.close(); response.release_conn()
   await storage.delete_file(file_key=saved.file_key)
   assert len(list(storage._client.list_objects(storage._bucket,recursive=True)))==0
  assert repository.add_file_metadata.await_count==2
  return {'status':'passed','cancelled_attempts':4,'compensated_objects':6,
   'exhausted_uploads':2,'successful_uploads':2,
   'cancelled_metadata_writes':0,'subsequent_download_integrity':True,'remaining_objects':0}
 finally: storage._client._http.clear()
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_cancellation_live_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_STREAM_CANCELLATION") != "1", reason="isolated real MinIO cancellation"
)
def test_real_minio_late_commit_is_compensated_after_cancellation():
    identity = uuid.uuid4().hex
    name = f"gpthub-s37-cancel-{identity}"
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
    try:
        networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-backend-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        minio_networks = json.loads(
            _checked(
                "inspect", "gpthub-dev-minio-1", "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        shared = sorted(set(networks) & set(minio_networks))
        assert len(shared) == 1, "dev network must be unambiguous"
        image = _checked("inspect", "gpthub-dev-minio-1", "--format", "{{.Image}}")
        assert image.startswith("sha256:")
        _checked(
            "create",
            "--name",
            name,
            "--label",
            f"gpthub.s37.cancellation={identity}",
            "--network",
            shared[0],
            "--memory",
            "512m",
            "--pids-limit",
            "128",
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
        result = _docker(
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            _PROBE,
            input=json.dumps(values).encode(),
            timeout=60,
        )
        report = _report(result)
        assert result.returncode == 0, (
            f"stream cancellation failed at {report.get('stage', 'unknown')}"
        )
        assert report == {
            "status": "passed",
            "cancelled_attempts": 4,
            "compensated_objects": 6,
            "exhausted_uploads": 2,
            "successful_uploads": 2,
            "cancelled_metadata_writes": 0,
            "subsequent_download_integrity": True,
            "remaining_objects": 0,
        }
    finally:
        if created:
            actual = _checked(
                "inspect", name, "--format", '{{index .Config.Labels "gpthub.s37.cancellation"}}'
            )
            assert actual == identity
            _checked("rm", "--force", "--volumes", name)
