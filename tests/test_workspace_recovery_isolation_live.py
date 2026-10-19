"""Opt-in installed-runtime admission of exact owned Docker recovery fixtures."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,sys,uuid
from pathlib import Path
sys.path.insert(0,'/opt/workspace-sidecar/service')
stage='source'
for path,digest in DIGESTS:
 assert hashlib.sha256(Path('/opt/workspace-sidecar/service',path).read_text(encoding='utf-8').encode()).hexdigest()==digest
from application.lifecycle import WorkspaceRegistry,WorkspaceNotFound
from application.recovery import LABEL_MANIFEST,mint_manifest
from domain.policy import WorkspacePolicy
from domain.ownership import mint
import drivers.docker_cli as module
native=module._docker; original_argv=module._create_argv
def fixture_argv(*args,**kwargs):
 values=original_argv(*args,**kwargs)
 values=['gpthub.workspace=0' if x=='gpthub.workspace=1' else x for x in values]
 if CASE=='violation': values[values.index('--network')+1]='bridge'
 if CASE=='memory':
  values[values.index('--memory')+1]='1073741824'
  values[values.index('--memory-swap')+1]='1073741824'
 if CASE=='pids': values[values.index('--pids-limit')+1]='512'
 if CASE=='cpu': values[values.index('--cpus')+1]='2.0'
 if CASE=='user': values[values.index('--user')+1]='0:0'
 if CASE=='quota':
  values=[x.replace('size=268435456','size=1073741824') for x in values]
 return values
module._create_argv=fixture_argv
async def main():
 global stage
 driver=module.DockerCliDriver(); ref=None; task=None
 owner='acceptance-'+uuid.uuid4().hex; wid=uuid.uuid4().hex
 policy=WorkspacePolicy(); fault=CASE=='unavailable'
 labels={LABEL_MANIFEST:mint_manifest(wid,owner,__import__('time').time()+600,policy)}
 try:
  stage='create'; ref=await driver.create(wid,policy,labels=labels)
  async def owned_inventory():
   code,raw,_=await native('inspect',ref.container_id); assert code==0
   data=json.loads(raw)[0]; assert data['Id']==ref.container_id
   return [module.ManagedContainer(ref,data['Config']['Labels'])]
  async def inspection(*args,**kwargs):
   if fault and args[0]=='inspect' and '--format' in args:
    return 1,'','synthetic-inspection-unavailable'
   return await native(*args,**kwargs)
  driver.list_managed=owned_inventory; module._docker=inspection
  registry=WorkspaceRegistry(driver)
  stage='recovery'; count=await registry.reconcile()
  if CASE in ('violation','memory','pids','cpu','user','quota'):
   assert count==0 and registry.count()==0
   try: registry.get(wid,owner,mint(wid,owner))
   except WorkspaceNotFound: pass
   else: raise AssertionError('unsafe_recovery')
   code,_,_=await native('inspect',ref.container_id); assert code!=0
  elif CASE=='unavailable':
   assert count==0 and registry.count()==1 and registry.health()['recovery_pending']==1
   try: registry.get(wid,owner,mint(wid,owner))
   except WorkspaceNotFound: pass
   else: raise AssertionError('unverified_recovery')
   code,_,_=await native('inspect',ref.container_id); assert code==0
   stage='retry'; fault=False
   assert await registry.reconcile()==1
   assert registry.health()['recovery_pending']==0
   assert registry.get(wid,owner,mint(wid,owner)).recovered
  else:
   assert count==1 and registry.count()==1
   assert registry.get(wid,owner,mint(wid,owner)).recovered
 finally:
  if ref is not None:
   module._docker=native
   await driver.destroy(ref)
   code,raw,_=await native('ps','-aq','--no-trunc','--filter',f'id={ref.container_id}')
   assert code==0 and not raw.strip()
try:
 asyncio.run(main())
 print(json.dumps({'status':'passed','case':CASE,'source_parity':True,'fixture_deleted':True}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_isolation_recovery_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_RECOVERY_ISOLATION") != "1", reason="owned Docker recovery isolation"
)
@pytest.mark.parametrize(
    "case", ["safe", "violation", "unavailable", "memory", "pids", "cpu", "user", "quota"]
)
def test_installed_runtime_rechecks_owned_container_before_recovery(case):
    root = Path(__file__).parents[1] / "service"
    paths = [
        "domain/policy.py",
        "application/lifecycle.py",
        "application/allocations.py",
        "application/recovery.py",
        "drivers/base.py",
        "drivers/docker_cli.py",
        "drivers/isolation.py",
        "infrastructure/container_operations.py",
    ]
    digests = [
        (path, hashlib.sha256((root / path).read_text(encoding="utf-8").encode()).hexdigest())
        for path in paths
    ]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(f"DIGESTS={digests!r}\nCASE={case!r}\n" + _PROBE).encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "recovery_isolation_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "recovery_isolation_failed_" + str(
        report.get("stage", "unknown")
    )
    assert report == {
        "status": "passed",
        "case": case,
        "source_parity": True,
        "fixture_deleted": True,
    }
