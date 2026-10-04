"""Opt-in Docker create completion withheld across preparation cancellation."""

import ast
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,re,sys,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.lifecycle import Workspace,WorkspaceRegistry
from application.documents.builds import DocumentBuildManager
from domain.files import write_command
from domain.policy import WorkspacePolicy
from drivers.base import ContainerRef
from drivers.docker_cli import DockerCliDriver
from infrastructure.document_compiler import DockerDocumentCompiler,CompilerFailure,_command
from infrastructure.document_cleanup import container_absent
import infrastructure.document_compiler as driver
stage='source_create'
async def main():
 global stage
 marker=uuid.uuid4().hex; source=''; compiler_id=''; task=None
 original=driver._command; fault=True; hide_named=False; entered=asyncio.Event(); release=asyncio.Event()
 policy=WorkspacePolicy()
 try:
  code,raw=await original('docker','create','--label',f'gpthub.document.acceptance={marker}',
   '--network','none','--read-only','--user','65534:65534','--cap-drop','ALL',
   '--security-opt','no-new-privileges','--memory','64m','--pids-limit','32',
   '--cpus','0.25','--tmpfs','/workspace:rw,size=16m,mode=1777',
   '--entrypoint','sleep',policy.image,'300'); assert code==0
  source=raw.decode().strip(); assert re.fullmatch('[0-9a-f]{64}',source)
  code,_=await original('docker','start',source); assert code==0
  registry=WorkspaceRegistry(DockerCliDriver())
  item=Workspace(marker,ContainerRef('docker',source),policy,1e12)
  cmd,payload=write_command('/workspace','paper/main.tex','fixture')
  result=await registry.exec_raw(item,cmd,stdin_payload=payload,max_output_chars=128)
  assert result.exit_code==0 and '__OK__' in result.stdout
  async def command(*args,**kwargs):
   if args[1]=='create':
    result=await original(*args,**kwargs)
    if SCENARIO=='timeout':
     entered.set(); raise CompilerFailure('runtime_unavailable')
    entered.set(); await release.wait(); return result
   if args[1:3]==('rm','-f') and args[-1]==compiler_id and fault:
    return 1,b''
   if args[1:3]==('ps','-aq') and '--filter' in args:
    if hide_named and any(value.startswith('name=^/gpthub-doc-') for value in args):
     return 0,b''
    args=(*args,'--filter',f'label=gpthub.document.workspace_container={source}')
   return await original(*args,**kwargs)
  driver._command=command
  compiler=DockerDocumentCompiler()
  stage='prepare_create'
  task=asyncio.create_task(compiler.prepare(item.ref,workspace_root='/workspace',project_path='/workspace/paper'))
  await asyncio.wait_for(entered.wait(),60)
  code,raw=await original('docker','ps','-aq','--no-trunc','--filter',
   f'label=gpthub.document.workspace_container={source}')
  values=raw.decode().splitlines(); assert code==0 and len(values)==1
  compiler_id=values[0].strip(); assert re.fullmatch('[0-9a-f]{64}',compiler_id)
  if SCENARIO=='timeout':
   stage='unknown_create_result'
   try: await asyncio.wait_for(task,30)
   except CompilerFailure as error: assert error.code=='runtime_unavailable'
   else: raise AssertionError('failure_lost')
   hide_named=True
   await compiler.reconcile()
   assert compiler.pending_preparation_cleanup==1
   hide_named=False
  else:
   stage='cancel_create'
   task.cancel(); await asyncio.sleep(0); assert not task.done()
   release.set()
   try: await asyncio.wait_for(task,30)
   except asyncio.CancelledError: pass
   else: raise AssertionError('cancellation_lost')
  assert compiler.pending_preparation_cleanup==1
  manager=DocumentBuildManager(compiler,None,None,max_jobs=1)
  assert manager._occupied_compiler_slots()==1
  assert not await container_absent(original,compiler_id)
  stage='retry_cleanup'
  fault=False
  await compiler.reconcile()
  assert compiler.pending_preparation_cleanup==0 and manager._occupied_compiler_slots()==0
  assert await container_absent(original,compiler_id)
  return {'create_drained':True,'outcome_preserved':True,'debt_capacity':True,'cleanup_retried':True}
 finally:
  release.set()
  if task is not None and not task.done(): task.cancel()
  if task is not None: await asyncio.gather(task,return_exceptions=True)
  driver._command=original
  if source:
   code,raw=await original('docker','ps','-aq','--no-trunc','--filter',
    f'label=gpthub.document.workspace_container={source}')
   assert code==0
   for value in raw.decode().splitlines():
    value=value.strip(); assert re.fullmatch('[0-9a-f]{64}',value)
    code,label=await original('docker','inspect','--format',
     '{{index .Config.Labels "gpthub.document.workspace_container"}}',value)
    assert code==0 and label.decode().strip()==source
    code,_=await original('docker','rm','-f',value); assert code==0
    assert await container_absent(original,value)
   if not await container_absent(original,source):
    code,label=await original('docker','inspect','--format',
     '{{index .Config.Labels "gpthub.document.acceptance"}}',source)
    assert code==0 and label.decode().strip()==marker
    code,_=await original('docker','rm','-f',source); assert code==0
    assert await container_absent(original,source)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_prepare_cancellation_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PREPARE_CANCEL") != "1", reason="explicit isolated Docker acceptance"
)
@pytest.mark.parametrize("scenario", ["cancel", "timeout"])
def test_actual_create_failure_retains_and_retries_owned_cleanup(scenario):
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=("SCENARIO=" + repr(scenario) + "\n" + _PROBE).encode(),
        capture_output=True,
        timeout=150,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "prepare_cancel_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "prepare_cancel_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "create_drained": True,
            "outcome_preserved": True,
            "debt_capacity": True,
            "cleanup_retried": True,
        },
    }
