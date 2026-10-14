"""Opt-in real disposable containers; inspection outage is injected locally."""

import ast
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,re,sys,time,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
from infrastructure.document_compiler import DockerDocumentCompiler,DOCUMENT_IMAGE,_command
from infrastructure.document_cleanup import container_absent
stage='create'
async def main():
 global stage
 owned=[]; marker=uuid.uuid4().hex
 try:
  for expiry in (int(time.time()+600),1,None):
   expiry_args=('--label',f'gpthub.document.expires_at={expiry}') if expiry is not None else ()
   code,raw=await _command('docker','create','--label','gpthub.document=1',
    '--label','gpthub.document.contract=1',*expiry_args,
    '--label',f'gpthub.document.acceptance={marker}','--network','none','--read-only',
    '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','64m',
    '--cpus','0.25','--pids-limit','32','--entrypoint','sleep',DOCUMENT_IMAGE,'300')
   assert code==0
   value=raw.decode().strip(); assert re.fullmatch('[0-9a-f]{64}',value)
   owned.append(value)
  running,expired,unknown=owned
  for value in (running,unknown):
   code,_=await _command('docker','start',value); assert code==0
  import infrastructure.document_compiler as driver
  original=driver._command; inject=True
  async def command(*args,**kwargs):
   if args[1:3]==('ps','-aq') and '--filter' in args:
    args=(*args,'--filter',f'label=gpthub.document.acceptance={marker}')
   if inject and args[1:3]==('inspect','--format') and args[-1]==running:
    return 1,b''
   return await original(*args,**kwargs)
  driver._command=command
  compiler=DockerDocumentCompiler()
  stage='inspection_outage'
  assert await compiler.reconcile()==1
  assert await container_absent(original,expired)
  code,state=await original('docker','inspect','--format','{{.State.Running}}',running)
  assert code==0 and state.strip()==b'true'
  assert compiler.cleanup_failures==2
  code,state=await original('docker','inspect','--format','{{.State.Running}}',unknown)
  assert code==0 and state.strip()==b'true'
  inject=False
  stage='healthy_reconcile'
  assert await compiler.reconcile()==0 and compiler.cleanup_failures==3
  stage='stopped_cleanup'
  code,_=await original('docker','stop','--time','1',running); assert code==0
  assert await compiler.reconcile()==1
  assert await container_absent(original,running)
  stage='idempotent_cleanup'
  assert await compiler.destroy(running) and compiler.cleanup_failures==4
  assert compiler.reconciled_cleanup==2
  code,state=await original('docker','inspect','--format','{{.State.Running}}',unknown)
  assert code==0 and state.strip()==b'true'
  return {'protected_live':True,'unknown_expiry_preserved':True,'removed_expired':True,'removed_stopped':True,
   'repeat_cleanup':True,'remaining':0}
 finally:
  if 'driver' in locals(): driver._command=original
  for value in owned:
   if await container_absent(_command,value): continue
   code,label=await _command('docker','inspect','--format',
    '{{index .Config.Labels "gpthub.document.acceptance"}}',value)
   assert code==0 and label.decode().strip()==marker
   code,_=await _command('docker','rm','-f',value); assert code==0
   assert await container_absent(_command,value)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_cleanup_live_probe_compiles_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_COMPILER_CLEANUP") != "1", reason="explicit isolated Docker acceptance"
)
def test_real_compiler_cleanup_preserves_live_containers_during_inspection_failure():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=90,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "compiler_cleanup_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "compiler_cleanup_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "protected_live": True,
            "unknown_expiry_preserved": True,
            "removed_expired": True,
            "removed_stopped": True,
            "repeat_cleanup": True,
            "remaining": 0,
        },
    }
