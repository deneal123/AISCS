"""Opt-in native Docker creation/start cancellation, without touching user sandboxes."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,importlib,importlib.abc,importlib.util,json,sys,uuid
from pathlib import Path
sys.path.insert(0,'/opt/workspace-sidecar/service')
stage='source'
source_map={name:(source,digest) for name,source,digest in SOURCES}
class SourceLoader(importlib.abc.MetaPathFinder,importlib.abc.Loader):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in source_map:
   return importlib.util.spec_from_loader(fullname,self,is_package=fullname=='drivers')
 def create_module(self,spec): return None
 def exec_module(self,module):
  source,digest=source_map[module.__name__]
  assert hashlib.sha256(source.encode()).hexdigest()==digest
  path=module.__name__.replace('.','/')
  module.__file__='/opt/workspace-sidecar/service/'+path+('.py' if path!='drivers' else '/__init__.py')
  if module.__name__=='drivers': module.__path__=['/opt/workspace-sidecar/service/drivers']
  exec(compile(source,module.__file__,'exec'),module.__dict__)
if REQUIRE_INSTALLED:
 for name,(source,digest) in source_map.items():
  path='drivers/__init__.py' if name=='drivers' else name.replace('.','/')+'.py'
  installed=Path('/opt/workspace-sidecar/service',path).read_text(encoding='utf-8')
  assert hashlib.sha256(installed.encode()).hexdigest()==digest
else: sys.meta_path.insert(0,SourceLoader())
import drivers.docker_cli as module
from application.lifecycle import WorkspaceRegistry,TooManyWorkspaces
from domain.policy import WorkspacePolicy
from infrastructure.container_operations import ContainerOperations
native=module._docker
argv=module._create_argv
module._create_argv=lambda *a,**kw: [
 'gpthub.workspace=0' if x=='gpthub.workspace=1' else x for x in argv(*a,**kw)]
async def main():
 global stage
 stage='signature'
 calls=[]
 class FailingDriver:
  async def create(self,*args,**kwargs):
   calls.append(kwargs)
   raise TypeError('synthetic-internal-signature-failure')
 try: await ContainerOperations(FailingDriver()).create('fixture',WorkspacePolicy(),{})
 except TypeError: pass
 else: raise AssertionError('internal_failure_lost')
 assert calls==[{'labels':{}}]
 entered=asyncio.Event(); ref=None; fault=FAIL_CLEANUP
 driver=module.DockerCliDriver(); destroy=driver.destroy
 async def command(*args,**kwargs):
  nonlocal ref
  if args[0]=='create':
   result=await native(*args,**kwargs)
   assert result[0]==0
   ref=module.ContainerRef('docker',result[1].strip())
   if UNKNOWN_REPLY:
    entered.set()
    await asyncio.Event().wait()
   return result
  if args[0]=='start':
   result=await native(*args,**kwargs)
   assert result[0]==0
   await driver.verify_isolation(ref,WorkspacePolicy())
   entered.set()
   await asyncio.Event().wait()
  return await native(*args,**kwargs)
 async def remove(owned):
  assert ref is not None and owned==ref
  if fault: raise module.DriverError('synthetic-cleanup-failure')
  await destroy(owned)
 module._docker=command; driver.destroy=remove
 registry=WorkspaceRegistry(driver,max_workspaces=1)
 task=asyncio.create_task(registry.create('acceptance-'+uuid.uuid4().hex,WorkspacePolicy()))
 try:
  stage='start'; await asyncio.wait_for(entered.wait(),60)
  stage='cancel'; task.cancel()
  try: await asyncio.wait_for(task,30)
  except asyncio.CancelledError: pass
  else: raise AssertionError('cancel_lost')
  assert not registry._reserved and not registry._items
  if UNKNOWN_REPLY:
   stage='uncertain'
   assert registry.count()==1 and registry.health()['creation_pending']==1
   async def empty_inventory(): return []
   driver.list_managed=empty_inventory
   assert await registry.reconcile()==0 and registry.count()==1
   async def owned_inventory():
    code,raw,_=await native('inspect',ref.container_id); assert code==0
    inspected=json.loads(raw)[0]
    assert inspected['Id']==ref.container_id
    return [module.ManagedContainer(ref,inspected['Config']['Labels'])]
   driver.list_managed=owned_inventory
   assert await registry.reconcile()==0
  assert registry.count()==int(FAIL_CLEANUP)
  if FAIL_CLEANUP:
   stage='debt'
   code,_,_=await native('inspect',ref.container_id); assert code==0
   try: await registry.create('other',WorkspacePolicy())
   except TooManyWorkspaces: pass
   else: raise AssertionError('capacity_lost')
   key,(owned,reason,attempts,_)=next(iter(registry._pending_cleanup.items()))
   registry._pending_cleanup[key]=(owned,reason,attempts,0)
   fault=False; await registry.reap()
  stage='absence'
  code,_,_=await native('inspect',ref.container_id)
  assert code!=0 and registry.count()==0
 finally:
  if not task.done(): task.cancel()
  await asyncio.gather(task,return_exceptions=True)
  if ref is not None:
   await destroy(ref)
   code,raw,_=await native('ps','-aq','--no-trunc','--filter',f'id={ref.container_id}')
   assert code==0 and not raw.strip()
try:
 asyncio.run(main())
 print(json.dumps({'status':'passed','source_parity':True,'container_absent':True,
  'cleanup_retried':FAIL_CLEANUP,'unknown_reply':UNKNOWN_REPLY}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_creation_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_CREATION_HANDOFF") != "1", reason="isolated Docker creation acceptance"
)
@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("unknown_reply", [False, True])
def test_real_container_cancelled_before_registry_handoff(cleanup_fails, unknown_reply):
    root = Path(__file__).parents[1] / "service"
    modules = [
        "domain.policy",
        "drivers.base",
        "drivers.creation_cleanup",
        "drivers.isolation",
        "drivers.docker_cli",
        "drivers",
        "infrastructure.container_operations",
        "application.lifecycle",
    ]
    sources = []
    for name in modules:
        relative = "drivers/__init__.py" if name == "drivers" else name.replace(".", "/") + ".py"
        source = (root / relative).read_text(encoding="utf-8")
        sources.append((name, source, hashlib.sha256(source.encode()).hexdigest()))
    installed = os.getenv("S37_CREATION_INSTALLED_RUNTIME") == "1"
    header = (
        f"SOURCES={sources!r}\nFAIL_CLEANUP={cleanup_fails!r}\nREQUIRE_INSTALLED={installed!r}\n"
        f"UNKNOWN_REPLY={unknown_reply!r}\n"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + _PROBE).encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "creation_handoff_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "creation_handoff_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "source_parity": True,
        "container_absent": True,
        "cleanup_retried": cleanup_fails,
        "unknown_reply": unknown_reply,
    }
