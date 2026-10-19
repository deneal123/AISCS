"""Opt-in exact-source child process with real isolated Docker cleanup."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from workspace_probe_sources import allocation_bootstrap

_PROBE = """
import asyncio,hashlib,json,sys,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
import application.lifecycle as lifecycle
from domain.policy import WorkspacePolicy
from drivers.docker_cli import DockerCliDriver,_docker
assert hashlib.sha256(SOURCE.encode()).hexdigest()==SOURCE_DIGEST
exec(compile(SOURCE,lifecycle.__file__,'exec'),lifecycle.__dict__)
stage='create'
class PublicationLock(asyncio.Lock):
 def __init__(self): super().__init__(); self.once=True
 async def __aenter__(self):
  if self.once:
   self.once=False; asyncio.current_task().cancel(); await asyncio.sleep(0)
  return await super().__aenter__()
class Driver(DockerCliDriver):
 def __init__(self):
  self.ref=None; self.entered=asyncio.Event(); self.fault=FAIL_CLEANUP
 async def create(self,*args,**kwargs):
  self.ref=await super().create(*args,**kwargs); return self.ref
 async def verify_isolation(self,ref,policy):
  await super().verify_isolation(ref,policy)
  self.entered.set()
  if CANCEL_STAGE=='publication': self.registry._lock=PublicationLock()
  else: await asyncio.Event().wait()
 async def destroy(self,ref):
  assert self.ref is not None and ref==self.ref
  if self.fault: raise RuntimeError('synthetic-cleanup-failure')
  await super().destroy(ref)
async def main():
 global stage
 driver=Driver(); registry=lifecycle.WorkspaceRegistry(driver,max_workspaces=1)
 driver.registry=registry
 task=asyncio.create_task(registry.create('acceptance-'+uuid.uuid4().hex,WorkspacePolicy()))
 try:
  await asyncio.wait_for(driver.entered.wait(),60)
  stage='cancel'
  if CANCEL_STAGE=='handoff':
   await registry._lock.acquire()
   try:
    task.cancel(); await asyncio.sleep(0)
    task.cancel(); await asyncio.sleep(0)
    task.cancel(); await asyncio.sleep(0)
    assert not task.done()
   finally: registry._lock.release()
  else: task.cancel()
  try: await asyncio.wait_for(task,30)
  except asyncio.CancelledError: pass
  else: raise AssertionError('cancel_lost')
  assert not registry._items and not registry._reserved
  assert registry.count()==int(FAIL_CLEANUP)
  if FAIL_CLEANUP:
   stage='retry'
   code,_,_=await _docker('inspect',driver.ref.container_id); assert code==0
   key,(ref,reason,attempts,_)=next(iter(registry._pending_cleanup.items()))
   registry._pending_cleanup[key]=(ref,reason,attempts,0)
   driver.fault=False
   assert await registry.reap()==1
  stage='absence'
  code,_,_=await _docker('inspect',driver.ref.container_id); assert code!=0
  assert registry.count()==0
  return {'isolation_verified':True,'cancel_preserved':True,'reservation_released':True,
   'cleanup_retried':FAIL_CLEANUP,'container_absent':True,'source_parity':True}
 finally:
  if not task.done(): task.cancel()
  await asyncio.gather(task,return_exceptions=True)
  if driver.ref is not None:
   driver.fault=False
   await driver.destroy(driver.ref)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_isolated_lifecycle_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORKSPACE_CANCEL") != "1", reason="isolated lifecycle Docker acceptance"
)
@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("cancel_stage", ["isolation", "publication", "handoff"])
def test_owned_docker_cleanup_after_creation_cancellation(cleanup_fails, cancel_stage):
    source = (Path(__file__).parents[1] / "service/application/lifecycle.py").read_text(
        encoding="utf-8"
    )
    header = (
        f"SOURCE={source!r}\nSOURCE_DIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
        f"FAIL_CLEANUP={cleanup_fails!r}\n"
        f"CANCEL_STAGE={cancel_stage!r}\n"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + allocation_bootstrap() + _PROBE).encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "lifecycle_cancel_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "lifecycle_cancel_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "checks": {
            "isolation_verified": True,
            "cancel_preserved": True,
            "reservation_released": True,
            "cleanup_retried": cleanup_fails,
            "container_absent": True,
            "source_parity": True,
        },
    }
