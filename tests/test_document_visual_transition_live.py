"""Installed durable-transition probe with synthetic attestation and private files."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILES = (
    "service/application/documents/builds.py",
    "service/application/documents/build_store.py",
    "service/application/documents/visual_transitions.py",
    "service/domain/documents/contracts.py",
)
_PROBE = """
import asyncio,hashlib,json,subprocess,sys,tempfile
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.documents import builds,build_store,visual_transitions
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentArtifact,DocumentBuild,contracts
stage='source'
async def main():
 global stage
 expected=json.load(sys.stdin)
 for module,digest in zip((builds,build_store,visual_transitions,contracts),expected['sources'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 with tempfile.TemporaryDirectory(prefix='visual-transition-') as directory:
  stage='fixture'; lock=asyncio.Lock()
  @asynccontextmanager
  async def operation(_item):
   async with lock: yield
  async def actual(_item,command,**kwargs):
   result=subprocess.run(['sh','-c',command],input=kwargs.get('stdin_payload'),capture_output=True,timeout=5)
   return SimpleNamespace(exit_code=result.returncode,stdout=result.stdout.decode(),truncated=False,timed_out=False)
  registry=SimpleNamespace(operation=operation,exec_raw=actual)
  item=SimpleNamespace(workspace_id='owned',policy=SimpleNamespace(root=directory))
  path=Path(directory)/'artifact'; path.write_bytes(b'private-synthetic-artifact')
  digest=hashlib.sha256(path.read_bytes()).hexdigest()
  build=DocumentBuild('probe','owned',directory+'/paper','generic_document',1,'rev','d'*64,'submission',True,
   state='visual_pending',artifacts=(DocumentArtifact('pdf','pdf','document.pdf','application/pdf',
    path.stat().st_size,digest,str(path)),))
  manager=builds.DocumentBuildManager(None,None,None)
  manager._builds[build.build_id]=build; manager._recovered_workspaces.add('owned')
  await manager.store.save(registry,item,build)
  original=manager.store.save
  async def unavailable(*args,**kwargs): raise RuntimeError('PRIVATE-RESPONSE')
  stage='claim_failure'; manager.store.save=unavailable
  try: await manager.claim_visual_audit(registry,item,build.build_id)
  except DocumentProjectError as error: assert error.code=='runtime_unavailable'
  else: raise AssertionError
  assert build.state=='visual_pending' and build.visual_audit_claimed_at is None
  manager.store.save=original
  stage='claim'; assert await manager.claim_visual_audit(registry,item,build.build_id) is build
  assert (await manager.store.load(registry,item))[0].state=='visual_audit'
  async def finish():
   return await manager.complete_visual_audit(registry,item,build.build_id,source_digest=build.source_digest,
    artifact_sha256=digest,passed=True,retryable=False,audit_version=1,diagnostics=[])
  stage='completion_failure'; manager.store.save=unavailable
  try: await finish()
  except DocumentProjectError as error: assert error.code=='runtime_unavailable'
  else: raise AssertionError
  assert build.state=='visual_audit'
  entered,release=asyncio.Event(),asyncio.Event()
  async def delayed(_registry,_item,candidate):
   assert candidate is not build and candidate.state=='ready'
   entered.set(); await release.wait(); await original(_registry,_item,candidate)
  manager.store.save=delayed; stage='completion_latch'
  task=asyncio.create_task(finish())
  try:
   await asyncio.wait_for(entered.wait(),2); assert build.state=='visual_audit'
   release.set(); assert await asyncio.wait_for(task,2) is build
  finally:
   release.set()
   if not task.done(): task.cancel()
   await asyncio.gather(task,return_exceptions=True)
  manager.store.save=original
  assert build.state=='ready' and (await manager.store.load(registry,item))[0].state=='ready'
  stage='fresh_recovery'; recovered=builds.DocumentBuildManager(None,None,None)
  await recovered.recover(registry,item)
  assert recovered.get('owned','probe').state=='ready'
  stage='postwrite_ack'; writes=0
  for action in ('complete','cancel'):
   subject=replace(build,build_id='lost-'+action,state='visual_pending',completed_at=None,
                   visual_audit_version=0,visual_audit_claimed_at=None)
   manager._builds[subject.build_id]=subject
   await original(registry,item,subject)
   async def lost(_registry,_item,candidate):
    nonlocal writes
    writes+=1; await original(_registry,_item,candidate)
    raise RuntimeError('PRIVATE-LOST-ACK')
   manager.store.save=lost
   if action=='cancel':
    assert await manager.cancel(registry,item,'owned',subject.build_id) is subject
    assert subject.state=='cancelled'
   else:
    assert await manager.complete_visual_audit(registry,item,subject.build_id,
     source_digest=subject.source_digest,artifact_sha256=digest,passed=True,
     retryable=False,audit_version=1,diagnostics=[]) is subject
    assert subject.state=='ready'
   assert not subject.manifest_uncertain
  assert writes==2
  manager.store.save=original
 return {'status':'passed','source_matches':True,'claim_failure_retained':True,
         'completion_failure_retained':True,'ready_after_ack_only':True,
         'fresh_manager_recovery':True,'postwrite_ack_settled':2,'postwrite_save_count':writes,
         'temporary_files_cleaned':not Path(directory).exists()}
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage}));sys.exit(1)
"""


def test_visual_transition_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_VISUAL_TRANSITION") != "1", reason="installed synthetic-transition probe"
)
def test_installed_visual_transitions_commit_only_after_acknowledgement():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps(
            {"sources": [hashlib.sha256((root / f).read_bytes()).hexdigest() for f in _FILES]}
        ),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0, "visual_transition_probe_failed_" + report.get(
        "stage", "unknown"
    )
    assert report == {
        "status": "passed",
        "source_matches": True,
        "claim_failure_retained": True,
        "completion_failure_retained": True,
        "ready_after_ack_only": True,
        "fresh_manager_recovery": True,
        "postwrite_ack_settled": 2,
        "postwrite_save_count": 2,
        "temporary_files_cleaned": True,
    }
