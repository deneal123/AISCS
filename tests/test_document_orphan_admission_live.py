"""Opt-in real orphan inventory with fresh manager processes and no build manifest."""

import ast
import json
import os
import subprocess

import pytest

_CHILD = """
import asyncio,json,sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from infrastructure.document_compiler import DockerDocumentCompiler
async def main(full):
 compiler=DockerDocumentCompiler()
 observed=await compiler.inventory_refs()
 assert len(observed)==(1 if full else 0)
 manager=DocumentBuildManager(compiler,None,None,max_jobs=1)
 manager.recover=AsyncMock()
 manager._reserve_manifest=AsyncMock()
 manager._start_reserved=AsyncMock(return_value='accepted')
 assert not manager._builds and not manager._tasks
 if full:
  try:
   await manager.start(None,SimpleNamespace(workspace_id='fixture'),project_path='paper',expected_revision='rev',final=False)
  except DocumentProjectError as error: assert error.code=='runtime_unavailable'
  else: raise AssertionError('orphan_admitted')
  manager._start_reserved.assert_not_awaited()
 else:
  assert await manager.start(None,SimpleNamespace(workspace_id='fixture'),project_path='paper',expected_revision='rev',final=False)=='accepted'
 assert manager._admission.preparing==0
 return {'empty_manifest':True,'inventory_count':len(observed),'allowed':not full}
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main(json.load(sys.stdin)))}))
except Exception:
 print(json.dumps({'status':'failed'}));raise SystemExit(1)
"""

_PROBE = """
import asyncio,json,re,sys,time,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
from infrastructure.document_compiler import DOCUMENT_IMAGE,_command
from infrastructure.document_cleanup import container_absent,compiler_inventory
stage='preflight'
async def main():
 global stage
 owned=''; marker=uuid.uuid4().hex
 try:
  # No filtering of the observed native inventory: prove the fixture is the
  # only compiler without touching unrelated resources.
  assert not await compiler_inventory(_command)
  stage='create_orphan'
  code,raw=await _command('docker','create','--label','gpthub.document=1',
   '--label','gpthub.document.contract=1','--label',f'gpthub.document.expires_at={int(time.time()+600)}',
   '--label',f'gpthub.document.acceptance={marker}','--network','none','--read-only',
   '--user','65534:65534','--cap-drop','ALL','--security-opt','no-new-privileges',
   '--memory','64m','--cpus','0.25','--pids-limit','32','--entrypoint','sleep',DOCUMENT_IMAGE,'300')
  assert code==0
  owned=raw.decode().strip();assert re.fullmatch('[0-9a-f]{64}',owned)
  code,_=await _command('docker','start',owned);assert code==0
  checks=[]
  for full in (True,False):
   stage='fresh_process_blocked' if full else 'fresh_process_released'
   if not full:
    code,label=await _command('docker','inspect','--format',
     '{{index .Config.Labels "gpthub.document.acceptance"}}',owned)
    assert code==0 and label.decode().strip()==marker
    code,_=await _command('docker','rm','-f',owned);assert code==0
    assert await container_absent(_command,owned)
   proc=await asyncio.create_subprocess_exec(sys.executable,'-c',CHILD,
    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
   try:
    raw,_=await asyncio.wait_for(proc.communicate(json.dumps(full).encode()),60)
   finally:
    if proc.returncode is None: proc.kill();await proc.wait()
   assert proc.returncode==0
   result=json.loads(raw);assert result['status']=='passed';checks.append(result['checks'])
  assert checks==[{'empty_manifest':True,'inventory_count':1,'allowed':False},
   {'empty_manifest':True,'inventory_count':0,'allowed':True}]
  return {'orphan_counted':True,'allocation_blocked':True,'absence_rechecked':True,'fresh_processes':2}
 finally:
  if owned and not await container_absent(_command,owned):
   code,label=await _command('docker','inspect','--format',
    '{{index .Config.Labels "gpthub.document.acceptance"}}',owned)
   assert code==0 and label.decode().strip()==marker
   code,_=await _command('docker','rm','-f',owned);assert code==0
   assert await container_absent(_command,owned)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage}));raise SystemExit(1)
"""


def test_orphan_admission_probe_parses_without_execution():
    ast.parse(_CHILD)
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_ORPHAN_ADMISSION") != "1", reason="explicit isolated Docker acceptance"
)
def test_real_manifestless_orphan_blocks_fresh_process_admission():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=("CHILD=" + repr(_CHILD) + "\n" + _PROBE).encode(),
        capture_output=True,
        timeout=150,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "orphan_admission_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "orphan_admission_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "orphan_counted": True,
            "allocation_blocked": True,
            "absence_rechecked": True,
            "fresh_processes": 2,
        },
    }
