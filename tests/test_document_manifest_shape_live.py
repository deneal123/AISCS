"""Real isolated filesystem fixtures for malformed registry directories/entries."""

import ast
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,re,shlex,sys,uuid
from types import SimpleNamespace
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.lifecycle import Workspace,WorkspaceRegistry
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentBuild
from domain.policy import WorkspacePolicy
from drivers.base import ContainerRef
from drivers.docker_cli import DockerCliDriver
from infrastructure.document_compiler import _command
from infrastructure.document_cleanup import container_absent
stage='create'
async def main():
 global stage
 marker=uuid.uuid4().hex; source=''; policy=WorkspacePolicy()
 try:
  code,raw=await _command('docker','create','--label',f'gpthub.document.acceptance={marker}',
   '--network','none','--read-only','--user','65534:65534','--cap-drop','ALL',
   '--security-opt','no-new-privileges','--memory','64m','--pids-limit','32',
   '--cpus','0.25','--tmpfs','/workspace:rw,size=16m,mode=1777',
   '--entrypoint','sleep',policy.image,'300'); assert code==0
  source=raw.decode().strip(); assert re.fullmatch('[0-9a-f]{64}',source)
  code,_=await _command('docker','start',source); assert code==0
  registry=WorkspaceRegistry(DockerCliDriver()); store=BuildManifestStore(); checks=[]; saves=[]
  for case in ('absent','file','jobs_symlink','parent_symlink','entry_symlink','entry_directory'):
   stage=case; root='/workspace/'+case
   item=Workspace('owned',ContainerRef('docker',source),WorkspacePolicy(root=root),1e12)
   build=DocumentBuild('job','owned',root+'/paper','generic_document',1,'revision','d'*64,'draft',False)
   payload=shlex.quote(json.dumps(build.manifest_dict()))
   private=root+'/.gpthub-document'; jobs=private+'/jobs'; outside=root+'/outside'
   script='set -eu; mkdir -p '+root+'; '
   if case=='file': script+='mkdir -p '+private+'; printf broken > '+jobs
   elif case=='jobs_symlink': script+='mkdir -p '+private+' '+outside+'; ln -s '+outside+' '+jobs
   elif case=='parent_symlink': script+='mkdir -p '+outside+'/jobs; ln -s '+outside+' '+private
   elif case=='entry_symlink': script+='mkdir -p '+jobs+'; printf %s '+payload+' > '+outside+'; ln -s '+outside+' '+jobs+'/job.json'
   elif case=='entry_directory': script+='mkdir -p '+jobs+'/job.json'
   code,_=await _command('docker','exec',source,'sh','-c',script); assert code==0
   rejected=False
   try: records=await store.load(registry,item)
   except RuntimeError: rejected=True
   checks.append(not rejected and not records if case=='absent' else rejected)
   refused=False
   try: await store.save(registry,item,build)
   except RuntimeError: refused=True
   saves.append(not refused if case=='absent' else refused)
  assert all(checks)
  assert all(saves)
  stage='duplicate_ids'; duplicates=0
  for same in (True,False):
   root='/workspace/duplicate-'+str(same); jobs=root+'/.gpthub-document/jobs'
   item=Workspace('owned',ContainerRef('docker',source),WorkspacePolicy(root=root),1e12)
   build=DocumentBuild('duplicate','owned',root+'/paper','generic_document',1,'rev','d'*64,'draft',False)
   first=build.manifest_dict(); second=dict(first) if same else dict(first,source_digest='e'*64)
   script='mkdir -p '+jobs+'; printf %s '+shlex.quote(json.dumps(first))+' > '+jobs+'/duplicate.json; printf %s '+shlex.quote(json.dumps(second))+' > '+jobs+'/alias.json'
   code,_=await _command('docker','exec',source,'sh','-c',script); assert code==0
   try: await store.load(registry,item)
   except RuntimeError: duplicates+=1
   else: raise AssertionError('duplicate_inventory_accepted')
  stage='delete_ack'; preserved=0
  item=Workspace('owned',ContainerRef('docker',source),WorkspacePolicy(root='/workspace/absent'),1e12)
  for flag in ('exit_code','truncated','timed_out'):
   build=DocumentBuild('expired-'+flag,'owned','/workspace/absent/paper','generic_document',1,'revision','d'*64,'draft',False)
   build.state='failed'; build.created_at=1; build.completed_at=2
   await store.save(registry,item,build)
   async def uncertain_exec(*args,**kwargs):
    result=await registry.exec_raw(*args,**kwargs)
    assert result.exit_code==0 and '__OK__' in result.stdout
    flags={'exit_code':0,'truncated':False,'timed_out':False}; flags[flag]=1 if flag=='exit_code' else True
    return SimpleNamespace(stdout=result.stdout,**flags)
   uncertain=SimpleNamespace(exec_raw=uncertain_exec,operation=registry.operation)
   manager=DocumentBuildManager(None,None,None); manager._builds[build.build_id]=build
   try: await manager._prune(uncertain,item)
   except DocumentProjectError: pass
   else: raise AssertionError('uncertain_delete_accepted')
   assert manager._builds[build.build_id] is build
   assert all(record.build_id!=build.build_id for record in await store.load(registry,item))
   await manager._prune(registry,item)
   assert build.build_id not in manager._builds
   preserved+=1
  return {'absent_empty':True,'malformed_shapes_rejected':5,'unsafe_writes_rejected':5,'uncertain_deletions_retained_until_retry':preserved,'duplicate_inventories_rejected':duplicates}
 finally:
  if source and not await container_absent(_command,source):
   code,label=await _command('docker','inspect','--format','{{index .Config.Labels "gpthub.document.acceptance"}}',source)
   assert code==0 and label.decode().strip()==marker
   code,_=await _command('docker','rm','-f',source); assert code==0
   assert await container_absent(_command,source)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_manifest_shape_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_MANIFEST_SHAPES") != "1", reason="isolated filesystem opt-in"
)
def test_real_manifest_inventory_rejects_non_directory_and_symlink_shapes():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=90,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "manifest_shape_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "manifest_shape_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "absent_empty": True,
            "malformed_shapes_rejected": 5,
            "unsafe_writes_rejected": 5,
            "uncertain_deletions_retained_until_retry": 3,
            "duplicate_inventories_rejected": 2,
        },
    }
