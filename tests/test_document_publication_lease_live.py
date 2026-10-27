"""Opt-in real PostgreSQL lease loss; source/storage/model boundaries are synthetic."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/services/chat/application/documents/publication/lease.py",
    "service/services/chat/application/documents/publication/service.py",
    "service/services/chat/persistence/documents/publication.py",
    "service/services/files/application/file_saver_service.py",
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
from service.services.chat.application.documents.publication import lease as lease
from service.services.chat.persistence.documents import publication as jobs
from service.services.files.application.file_saver_service import FileSaverService

stage='source_parity'
async def main():
 global stage
 modules=(lease.__file__,service.__file__,jobs.__file__,
  sys.modules[FileSaverService.__module__].__file__)
 assert len(sys.argv[1:])==len(modules)
 assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected
  for path,expected in zip(modules,sys.argv[1:],strict=True))
 cfg=Config(); assert cfg.pg.host=='postgres'
 connector=PgConnector(cfg.pg,force_new=True)
 identity=uuid.uuid4().hex; fixture=None; owner=None; cleaned=False; checks={}
 try:
  stage='fixture'
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'})
   assert owner is not None
   rows=await jobs.enqueue(db,user_id=owner,thread_id=identity,workspace_id=identity,
    billing_job_id=identity,attach_to_latest=False,descriptors=({
     'build_id':identity,'artifact_id':identity,'role':'pdf','source_digest':'a'*64,
     'artifact_sha256':hashlib.sha256(b'onetwo').hexdigest(),'artifact_size':6,
     'filename':'acceptance.pdf','mime_type':'application/pdf'},))
   fixture=rows[0]['id']; token=uuid.uuid4()
   # Future scheduling protects even an intentionally expired fixture lease
   # from the shared worker. Only this exact synthetic row is changed/deleted.
   await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
    "lease_expires_at=clock_timestamp()+interval '600 seconds',"
    "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id AND user_id=:owner"),
    {'token':token,'id':fixture,'owner':owner})
   await db.commit()

  async def reset(expired=False):
   nonlocal token
   token=uuid.uuid4()
   async with connector.get_session_context() as db:
    result=await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
     "lease_expires_at=clock_timestamp()+(:seconds * interval '1 second') "
     "WHERE id=:id AND user_id=:owner"),
     {'token':token,'seconds':-1 if expired else 600,'id':fixture,'owner':owner})
    assert result.rowcount==1; await db.commit()
    return dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
     'WHERE id=:id AND user_id=:owner'),{'id':fixture,'owner':owner})).mappings().one())

  async def revoke():
   async with connector.get_session_context() as db:
    result=await db.execute(text('UPDATE profile.document_publication_job SET lease_token=:new '
     'WHERE id=:id AND user_id=:owner AND lease_token=:old'),
     {'new':uuid.uuid4(),'old':token,'id':fixture,'owner':owner})
    assert result.rowcount==1; await db.commit()

  for mode in ('expired','read','upload'):
   stage=mode
   row=await reset(expired=mode=='expired')
   repository=SimpleNamespace(fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
    add_file_metadata=AsyncMock())
   async def upload(**kwargs):
    assert kwargs['stream'].read()==b'onetwo'
    if mode=='upload': await revoke()
    return 'internal://object'
   storage=SimpleNamespace(build_file_path=lambda *_:'uploads/CHAT/opaque.pdf',
    upload_file_stream=AsyncMock(side_effect=upload),delete_file=AsyncMock())
   files=FileSaverService(repository,'uploads',storage)
   closed=asyncio.Event()
   async def chunks():
    try:
     yield b'one'
     if mode=='read':
      await revoke()
      await asyncio.Event().wait()
     yield b'two'
    finally: closed.set()
   download=SimpleNamespace(chunks=chunks,close=AsyncMock())
   audit=AsyncMock(return_value='ready'); defer=AsyncMock(); finalized=AsyncMock()
   with (
    patch.object(lease,'_HEARTBEAT_INTERVAL',0.02),
    patch.object(service,'_settle_pending_audit',AsyncMock()),
    patch.object(service,'read_binding',AsyncMock(return_value={'workspace_id':identity})),
    patch.object(service,'_agent_ref',lambda *_:{}),
    patch.object(service,'_ensure_audited_durable',audit),
    patch.object(service,'document_build_status',AsyncMock(return_value={'state':'ready'})),
    patch.object(service,'_matching_artifact',lambda *_:True),
    patch.object(service,'stream_document_artifact',AsyncMock(return_value=download)),
    patch.object(jobs,'defer',defer),patch.object(jobs,'delivered',finalized),
   ):
    tasks=asyncio.all_tasks()
    async with connector.get_session_context() as db:
     outcome=await asyncio.wait_for(service.deliver_one(config=cfg,pg_connector=connector,
      redis=object(),file_service=files,session=db,row=row),timeout=3)
    assert outcome=='deferred'
    repository.add_file_metadata.assert_not_awaited()
    defer.assert_not_awaited(); finalized.assert_not_awaited()
    assert asyncio.all_tasks()==tasks
    if mode=='expired':
     audit.assert_not_awaited(); download.close.assert_not_awaited()
    else:
     download.close.assert_awaited_once(); assert closed.is_set()
    if mode in ('expired','read'):
     storage.upload_file_stream.assert_not_awaited(); storage.delete_file.assert_not_awaited()
    else:
     storage.upload_file_stream.assert_awaited_once()
     storage.delete_file.assert_awaited_once_with(file_key='uploads/CHAT/opaque.pdf')
    checks[mode]=True

  for mode in ('terminal_binding','terminal_audit'):
   stage=mode
   row=await reset()
   async def missing_binding(*args):
    await revoke()
    return None
   async def rejected_audit(**kwargs):
    await revoke()
    return 'artifact_invalid'
   binding=AsyncMock(return_value={'workspace_id':identity})
   audit=AsyncMock(side_effect=rejected_audit)
   if mode=='terminal_binding': binding.side_effect=missing_binding
   download=AsyncMock(); files=SimpleNamespace(save_stream=AsyncMock())
   with (
    patch.object(service,'_settle_pending_audit',AsyncMock()),
    patch.object(service,'read_binding',binding),
    patch.object(service,'_agent_ref',lambda *_:{}),
    patch.object(service,'_ensure_audited_durable',audit),
    patch.object(service,'stream_document_artifact',download),
   ):
    async with connector.get_session_context() as db:
     assert await service.deliver_one(config=cfg,pg_connector=connector,
      redis=object(),file_service=files,session=db,row=row)=='deferred'
     # Exercise the production worker's outer commit too. Failed CAS must not
     # release the new holder's token or change its durable retry/terminal state.
     await db.commit()
     current=dict((await db.execute(text('SELECT * FROM profile.document_publication_job '
      'WHERE id=:id AND user_id=:owner'),{'id':fixture,'owner':owner})).mappings().one())
    assert current['lease_token']!=row['lease_token']
    for field in ('status','attempts','failure_code','next_attempt_at','user_file_id'):
     assert current[field]==row[field]
    download.assert_not_awaited(); files.save_stream.assert_not_awaited()
    if mode=='terminal_binding': audit.assert_not_awaited()
   checks[mode]=True
 finally:
  stage_before_cleanup=stage; stage='cleanup'
  if fixture is not None:
   async with connector.get_session_context() as db:
    await db.execute(text('DELETE FROM profile.document_publication_job '
     'WHERE id=:id AND user_id=:owner AND thread_id=:thread'),
     {'id':fixture,'owner':owner,'thread':identity})
    await db.commit()
    remaining=await db.scalar(text('SELECT count(*) FROM profile.document_publication_job '
     'WHERE id=:id'),{'id':fixture})
    assert remaining==0; cleaned=True
  stage=stage_before_cleanup
 assert cleaned
 print(json.dumps({'status':'passed','checks':checks,'fixture_cleaned':True}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_lease_probe_source_is_valid():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PUBLICATION_LEASE") != "1", reason="opt-in isolated dev PostgreSQL"
)
def test_real_lease_loss_prevents_audit_and_library_creation():
    expected = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _MODULES]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-", *expected],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "bounded lease report missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, f"lease proof failed at {report.get('stage', 'unknown')}"
    assert report == {
        "status": "passed",
        "checks": {
            "expired": True,
            "read": True,
            "upload": True,
            "terminal_binding": True,
            "terminal_audit": True,
        },
        "fixture_cleaned": True,
    }
