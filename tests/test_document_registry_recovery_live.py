"""Opt-in fresh-process recovery using real manifests and owned Docker fixtures."""

import ast
import json
import os
import subprocess

import pytest

_CHILD = """
import asyncio,json,sys,time
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.lifecycle import Workspace,WorkspaceRegistry
from application.documents.builds import DocumentBuildManager
from application.documents.build_store import BuildManifestStore
from application.documents.projects import DocumentProjectError
from domain.policy import WorkspacePolicy
from drivers.base import ContainerRef
from drivers.docker_cli import DockerCliDriver
from infrastructure.document_compiler import DockerDocumentCompiler
import infrastructure.document_compiler as driver
async def main(data):
 registry=WorkspaceRegistry(DockerCliDriver())
 item=Workspace(data['workspace'],ContainerRef('docker',data['source']),WorkspacePolicy(),time.time()+600)
 registry._items[item.workspace_id]=item
 original=driver._command
 inventory_fault=data.get('maintenance_fault',False) and data['outage']
 async def command(*args,**kwargs):
  nonlocal inventory_fault
  if inventory_fault and args[1:3]==('ps','-aq') and 'label=gpthub.document=1' in args:
   inventory_fault=False; return 0,bytes((255,))
  if args[1:3]==('ps','-aq') and '--filter' in args:
   args=(*args,'--filter',f"label=gpthub.document.acceptance={data['marker']}")
  if data['outage'] and args[1:3]==('rm','-f') and args[-1]==data['compiler']:
   return 1,b''
  return await original(*args,**kwargs)
 driver._command=command
 manager=DocumentBuildManager(DockerDocumentCompiler(),None,None,max_jobs=1)
 await manager.reconcile_registry(registry)
 build=manager.get(item.workspace_id,data['build'])
 assert build is not None and build.state=='failed' and build.failure_code=='build_interrupted'
 assert not manager._pending_recovery
 if data.get('maintenance_fault',False) and data['outage']:
  assert manager.health()['reconciliation_unavailable']
  assert manager.health()['reconciliation_failures']==1
  try:
   await manager.start(registry,item,project_path='paper',expected_revision='rev',final=False)
  except DocumentProjectError as error: assert error.code=='runtime_unavailable'
  else: raise AssertionError('outage_admission_allowed')
  await manager.reconcile_registry(registry)
  assert not manager.health()['reconciliation_unavailable']
 if data['outage']:
  assert build.compiler_ref==data['compiler'] and manager._occupied_compiler_slots()==1
  try:
   await manager.start(registry,item,project_path='paper',expected_revision='rev',final=False)
  except DocumentProjectError as error:
   assert error.code=='runtime_unavailable'
  else:
   raise AssertionError('admission_allowed')
 else:
  assert not build.compiler_ref and manager._occupied_compiler_slots()==0
 records=await BuildManifestStore().load(registry,item)
 assert len(records)==1 and records[0].compiler_ref==build.compiler_ref
 if data.get('retire',False):
  assert not build.compiler_ref
  await registry.destroy(item.workspace_id)
  await manager.reconcile_registry(registry)
  assert manager.get(item.workspace_id,data['build']) is None
  assert not manager._builds and not manager._recovered_workspaces
  assert manager.health()['failed']==0
 return {'recovered':True,'cleanup_pending':bool(build.compiler_ref),'capacity':manager._occupied_compiler_slots()}
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main(json.load(sys.stdin)))}))
except Exception:
 print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""

_PROBE = """
import asyncio,json,re,sys,time,uuid
from types import SimpleNamespace
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.lifecycle import Workspace,WorkspaceRegistry
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.build_preparation import prepare_build
from domain.documents import DocumentBuild,load_profile_catalog
from domain.files import write_command
from domain.policy import WorkspacePolicy
from drivers.base import ContainerRef
from drivers.docker_cli import DockerCliDriver
from infrastructure.document_compiler import DOCUMENT_IMAGE,DockerDocumentCompiler,_command
import infrastructure.document_compiler as driver
from infrastructure.document_cleanup import container_absent
stage='create'
async def main():
 global stage
 owned=[]; marker=uuid.uuid4().hex; build_id='build-'+marker
 policy=WorkspacePolicy(); source=''
 try:
  fixtures=[('source',policy.image)]
  if not REFERENCE.startswith('journal'): fixtures.append(('compiler',DOCUMENT_IMAGE))
  for kind,image in fixtures:
   args=['docker','create','--label',f'gpthub.document.acceptance={marker}',
    '--network','none','--read-only','--user','65534:65534','--cap-drop','ALL',
    '--security-opt','no-new-privileges','--memory','64m','--cpus','0.25',
    '--pids-limit','32','--tmpfs','/workspace:rw,size=16m,mode=1777']
   if kind=='compiler':
    args+=['--name',f'gpthub-doc-{build_id}','--label','gpthub.document=1',
     '--label','gpthub.document.contract=1','--label',f'gpthub.document.workspace_container={source}',
     '--label',f'gpthub.document.expires_at={int(time.time()+600)}']
   code,raw=await _command(*args,'--entrypoint','sleep',image,'300'); assert code==0
   value=raw.decode().strip(); assert re.fullmatch('[0-9a-f]{64}',value)
   owned.append(value)
   code,_=await _command('docker','start',value); assert code==0
   if kind=='source': source=value
  registry=WorkspaceRegistry(DockerCliDriver())
  item=Workspace(marker,ContainerRef('docker',source),policy,time.time()+600)
  if REFERENCE.startswith('journal'):
   stage='native_prepare_journal'
   cmd,payload=write_command('/workspace','paper/main.tex','fixture')
   result=await registry.exec_raw(item,cmd,stdin_payload=payload,max_output_chars=128)
   assert result.exit_code==0 and '__OK__' in result.stdout
   async def manifest(*args): return {},load_profile_catalog().get('generic_article')
   async def digest(*args): return 'd'*64
   async def revision(*args): return 'revision'
   async def command(*args,**kwargs):
    if args[1]=='create': args=(*args[:2],'--label',f'gpthub.document.acceptance={marker}',*args[2:])
    return await _command(*args,**kwargs)
   driver._command=command
   try:
    manager=DocumentBuildManager(DockerDocumentCompiler(),SimpleNamespace(manifest=manifest,digest=digest),revision)
    record,prepared,_=await prepare_build(manager,registry,item,project_path='paper',
     expected_revision='revision',final=False)
    compiler=prepared.container_id; owned.append(compiler); build_id=record.build_id
    records=await BuildManifestStore().load(registry,item)
    assert len(records)==1 and records[0].state=='preparing' and records[0].compiler_ref==compiler
   finally: driver._command=_command
  else:
   compiler=owned[1]
   record=DocumentBuild(build_id,marker,'/workspace/paper','generic_document',1,
    'revision','d'*64,'draft',False,state='preparing',
    compiler_ref=compiler if REFERENCE=='id' else f'gpthub-doc-{build_id}')
   stage='manifest_save'
   async with registry.operation(item): await BuildManifestStore().save(registry,item,record)
  data={'marker':marker,'workspace':marker,'build':build_id,'source':source,'compiler':compiler,
   'maintenance_fault':REFERENCE=='journal_maintenance'}
  results=[]
  for outage in (True,False):
   stage='retained_cleanup' if outage else 'fresh_process_cleanup'
   data['outage']=outage
   proc=await asyncio.create_subprocess_exec(sys.executable,'-c',CHILD,
    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
   raw,_=await asyncio.wait_for(proc.communicate(json.dumps(data).encode()),60)
   assert proc.returncode==0
   result=json.loads(raw); assert result['status']=='passed'; results.append(result['checks'])
  assert results==[{'recovered':True,'cleanup_pending':True,'capacity':1},
   {'recovered':True,'cleanup_pending':False,'capacity':0}]
  assert await container_absent(_command,compiler)
  if REFERENCE=='retired':
   stage='retired_inventory'
   data['outage']=False; data['retire']=True
   proc=await asyncio.create_subprocess_exec(sys.executable,'-c',CHILD,
    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
   raw,_=await asyncio.wait_for(proc.communicate(json.dumps(data).encode()),60)
   assert proc.returncode==0 and json.loads(raw)['status']=='passed'
   assert await container_absent(_command,source)
  return {'fresh_processes':2,'retained_capacity':True,'durable_reference':True,'cleanup_retry':True}
 finally:
  for value in reversed(owned):
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


def test_fresh_process_recovery_probe_parses_without_execution():
    ast.parse(_CHILD)
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_REGISTRY_RECOVERY") != "1", reason="explicit isolated Docker acceptance"
)
@pytest.mark.parametrize("reference", ["id", "name", "journal", "journal_maintenance", "retired"])
def test_real_manifest_recovery_across_processes_retains_capacity_until_cleanup(reference):
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=("REFERENCE=" + repr(reference) + "\nCHILD=" + repr(_CHILD) + "\n" + _PROBE).encode(),
        capture_output=True,
        timeout=150,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "registry_recovery_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "registry_recovery_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "fresh_processes": 2,
            "retained_capacity": True,
            "durable_reference": True,
            "cleanup_retry": True,
        },
    }
