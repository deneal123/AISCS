"""Exact-source registry recovery/expiry against an owned Docker inventory."""

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
from domain.ownership import OwnershipError
import drivers.docker_cli as driver_module
assert hashlib.sha256(SOURCE.encode()).hexdigest()==SOURCE_DIGEST
assert hashlib.sha256(DRIVER_SOURCE.encode()).hexdigest()==DRIVER_DIGEST
exec(compile(SOURCE,lifecycle.__file__,'exec'),lifecycle.__dict__)
exec(compile(DRIVER_SOURCE,driver_module.__file__,'exec'),driver_module.__dict__)
DockerCliDriver=driver_module.DockerCliDriver; _docker=driver_module._docker
stage='create'
class Driver(DockerCliDriver):
 def __init__(self): self.ref=None; self.fault=False
 async def create(self,*args,**kwargs):
  self.ref=await super().create(*args,**kwargs); return self.ref
 async def list_managed(self):
  return [item for item in await super().list_managed() if item.ref==self.ref]
 async def destroy(self,ref):
  assert self.ref is not None and ref==self.ref
  if self.fault: raise RuntimeError('synthetic-expiry-cleanup-failure')
  await super().destroy(ref)
async def main():
 global stage
 driver=Driver(); owner='acceptance-'+uuid.uuid4().hex
 original=lifecycle.WorkspaceRegistry(driver,max_workspaces=1)
 try:
  item,token=await original.create(owner,WorkspacePolicy(),ttl_sec=1 if EXPIRED else 60)
  await driver.verify_isolation(item.ref,item.policy)
  recovered=lifecycle.WorkspaceRegistry(driver,max_workspaces=1)
  if EXPIRED:
   await asyncio.sleep(1.2)
   driver.fault=True; stage='expiry_reconcile'
   assert await recovered.reconcile()==0
   stage='expiry_debt'
   assert not recovered._items and recovered.count()==1
   assert recovered.health()['pending_cleanup']==1
   try: recovered.get(item.workspace_id,owner,token)
   except (lifecycle.WorkspaceNotFound,OwnershipError): pass
   else: raise AssertionError('expired_access')
   code,_,_=await _docker('inspect',item.ref.container_id); assert code==0
   key,(ref,reason,attempts,_)=next(iter(recovered._pending_cleanup.items()))
   assert reason=='expired' and attempts==1
   recovered._pending_cleanup[key]=(ref,reason,attempts,0)
   driver.fault=False; stage='expiry_retry'
   assert await recovered.reap()==1
   assert recovered.health()['expired_cleanup']==1
  else:
   stage='recover_active'
   assert await recovered.reconcile()==1
   stage='recovered_owner'
   restored=recovered.get(item.workspace_id,owner,token)
   assert restored.recovered and restored.ref==item.ref and restored.policy==item.policy
   assert await recovered.reconcile()==0 and recovered.count()==1
   stage='explicit_cleanup'
   await recovered.destroy(restored.workspace_id)
  stage='absence'
  code,raw,_=await _docker('ps','-aq','--no-trunc','--filter',f'id={item.ref.container_id}')
  assert code==0 and not raw.strip() and recovered.count()==0
  return {'signed_manifest':True,'owner_token_preserved':not EXPIRED,
   'expired_denied':EXPIRED,'cleanup_retried':EXPIRED,'container_absent':True,'source_parity':True}
 finally:
  if driver.ref is not None:
   driver.fault=False; await driver.destroy(driver.ref)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_recovery_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORKSPACE_RECOVERY") != "1", reason="owned lifecycle Docker acceptance"
)
@pytest.mark.parametrize("expired", [False, True])
def test_signed_manifest_recovery_and_expired_cleanup(expired):
    source = (Path(__file__).parents[1] / "service/application/lifecycle.py").read_text(
        encoding="utf-8"
    )
    driver_source = (Path(__file__).parents[1] / "service/drivers/docker_cli.py").read_text(
        encoding="utf-8"
    )
    header = (
        f"SOURCE={source!r}\nSOURCE_DIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
        f"EXPIRED={expired!r}\n"
        f"DRIVER_SOURCE={driver_source!r}\n"
        f"DRIVER_DIGEST={hashlib.sha256(driver_source.encode()).hexdigest()!r}\n"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + allocation_bootstrap() + _PROBE).encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "workspace_recovery_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "workspace_recovery_failed_" + str(
        report.get("stage", "unknown")
    )
    assert report == {
        "status": "passed",
        "checks": {
            "signed_manifest": True,
            "owner_token_preserved": not expired,
            "expired_denied": expired,
            "cleanup_retried": expired,
            "container_absent": True,
            "source_parity": True,
        },
    }
