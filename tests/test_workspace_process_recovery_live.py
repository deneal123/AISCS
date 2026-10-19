"""Owned Docker lifecycle across two actual interpreter processes."""

import ast
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from workspace_probe_sources import allocation_bootstrap

_PROBE = """
import asyncio,hashlib,json,os,sys
sys.path.insert(0,'/opt/workspace-sidecar/service')
import application.lifecycle as lifecycle
import drivers.docker_cli as driver_module
from application.recovery import LABEL_MANIFEST,parse_manifest,owner_binding
from domain.policy import WorkspacePolicy
from domain import ownership
from drivers.base import ContainerRef,ManagedContainer
for module,key in ((lifecycle,'lifecycle'),(driver_module,'driver')):
 source=SOURCES[key]
 assert hashlib.sha256(source.encode()).hexdigest()==DIGESTS[key]
 exec(compile(source,module.__file__,'exec'),module.__dict__)
# The running service must not adopt/reap this separately owned acceptance
# container. Its private registry still reads the same signed manifest.
native_argv=driver_module._create_argv
def fixture_argv(*args,**kwargs):
 return ['gpthub.workspace=0' if value=='gpthub.workspace=1' else value
  for value in native_argv(*args,**kwargs)]
driver_module._create_argv=fixture_argv
owner='process-acceptance-'+MARKER
stage=MODE
class Driver(driver_module.DockerCliDriver):
 async def list_managed(self):
  code,raw,_=await driver_module._docker('ps','-aq','--no-trunc','--filter',f'name=^/gpthub-ws-{MARKER}$')
  assert code==0
  ids=set(raw.splitlines())
  if not ids: return []
  found=[]
  for container_id in ids:
   code,details,_=await driver_module._docker('inspect','--format','{{json .Config.Labels}}',container_id)
   assert code==0
   found.append(ManagedContainer(ContainerRef(self.name,container_id),json.loads(details)))
  assert len(found)==len(ids)==1
  for item in found:
   manifest=parse_manifest(item.labels.get(LABEL_MANIFEST))
   assert manifest is not None and manifest.workspace_id==MARKER
   assert manifest.owner_binding==owner_binding(MARKER,owner)
  return found
async def main():
 driver=Driver(); registry=lifecycle.WorkspaceRegistry(driver,max_workspaces=1)
 if MODE=='prepare':
  lifecycle.secrets.token_hex=lambda size: MARKER
  item,_=await registry.create(owner,WorkspacePolicy(),ttl_sec=1 if EXPIRED else 60)
  await driver.verify_isolation(item.ref,item.policy)
  assert registry.count()==1
  print(json.dumps({'status':'prepared'}),flush=True)
  # Intentionally bypass asyncio teardown and every finally in this process.
  os._exit(0)
 if MODE=='cleanup':
  for item in await driver.list_managed(): await driver.destroy(item.ref)
  assert not await driver.list_managed()
  return {'status':'cleaned'}
 if EXPIRED: await asyncio.sleep(1.2)
 count=await registry.reconcile()
 if EXPIRED:
  assert count==0 and registry.count()==0
  assert registry.health()['expired_cleanup']==1
 else:
  assert count==1 and registry.health()['recovered']==1
  # Recovery preserves owner binding; a newly issued owned capability works.
  item=registry.get(MARKER,owner,ownership.mint(MARKER,owner,ttl_sec=30))
  assert item.recovered
  await registry.destroy(MARKER)
 assert not await driver.list_managed() and registry.count()==0
 return {'status':'passed','checks':{'separate_process':True,'signed_recovery':not EXPIRED,
  'expired_cleanup':EXPIRED,'container_absent':True,'source_parity':True}}
try:
 print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_process_recovery_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORKSPACE_PROCESS_RECOVERY") != "1",
    reason="isolated two-process Docker acceptance",
)
@pytest.mark.parametrize("expired", [False, True])
def test_registry_survives_actual_interpreter_exit(expired):
    root = Path(__file__).parents[1] / "service"
    sources = {
        "lifecycle": (root / "application/lifecycle.py").read_text(encoding="utf-8"),
        "driver": (root / "drivers/docker_cli.py").read_text(encoding="utf-8"),
    }
    digests = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in sources.items()}
    marker = uuid.uuid4().hex[:16]

    def run(mode):
        header = (
            f"SOURCES={sources!r}\nDIGESTS={digests!r}\nMARKER={marker!r}\n"
            f"EXPIRED={expired!r}\nMODE={mode!r}\n"
        )
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
            input=(header + allocation_bootstrap() + _PROBE).encode(),
            capture_output=True,
            timeout=120,
            check=False,
        )
        lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
        assert lines, "process_recovery_report_missing"
        report = json.loads(lines[-1])
        assert result.returncode == 0, "process_recovery_failed_" + str(
            report.get("stage", "unknown")
        )
        return report

    try:
        assert run("prepare") == {"status": "prepared"}
        assert run("recover") == {
            "status": "passed",
            "checks": {
                "separate_process": True,
                "signed_recovery": not expired,
                "expired_cleanup": expired,
                "container_absent": True,
                "source_parity": True,
            },
        }
    finally:
        assert run("cleanup") == {"status": "cleaned"}
