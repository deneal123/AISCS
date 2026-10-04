"""Opt-in deployed-image privacy probe; no user data or Docker workloads are created."""

import ast
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,logging,sys
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.lifecycle import WorkspaceRegistry
from drivers import docker_cli
from drivers.base import ContainerRef,DriverError
class Capture(logging.Handler):
 def __init__(self): super().__init__(); self.records=[]
 def emit(self,record): self.records.append(record)
async def main():
 marker='synthetic-private-marker'
 capture=Capture(); loggers=[logging.getLogger(name) for name in
  ('workspace-sidecar.core','workspace-sidecar.docker')]
 original=[(logger.level,logger.propagate) for logger in loggers]
 for logger in loggers:
  logger.addHandler(capture); logger.setLevel(logging.ERROR); logger.propagate=False
 registry=WorkspaceRegistry(None); retried=asyncio.Event(); calls=0; task=None
 original_docker=docker_cli._docker
 async def reap():
  nonlocal calls
  calls+=1
  if calls==1: raise RuntimeError(marker)
  retried.set()
 async def reconcile(): pass
 async def failed_docker(*args,**kwargs): raise DriverError(marker)
 try:
  registry.reap=reap; registry.reconcile=reconcile
  task=asyncio.create_task(registry.reap_forever(interval_sec=0))
  await asyncio.wait_for(retried.wait(),2)
  task.cancel(); await asyncio.gather(task,return_exceptions=True)
  docker_cli._docker=failed_docker
  await docker_cli.DockerCliDriver()._kill_process_group(ContainerRef('docker',marker))
  assert len(capture.records)==2
  assert [record.failure_code for record in capture.records]==['maintenance_failed','process_cleanup_failed']
  assert all(record.exc_info is None and marker not in record.getMessage() for record in capture.records)
  assert all(set(vars(record))-set(vars(logging.LogRecord('',0,'',0,'',(),None)))
   <= {'component','failure_code'} for record in capture.records)
  return {'maintenance_redacted':True,'cleanup_redacted':True,'retry_survived':True}
 finally:
  if task is not None and not task.done(): task.cancel(); await asyncio.gather(task,return_exceptions=True)
  docker_cli._docker=original_docker
  for logger,(level,propagate) in zip(loggers,original):
   logger.removeHandler(capture); logger.setLevel(level); logger.propagate=propagate
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except Exception:
 print(json.dumps({'status':'failed','code':'maintenance_privacy_failed'})); raise SystemExit(1)
"""


def test_deployed_privacy_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_MAINTENANCE_PRIVACY") != "1", reason="deployed privacy opt-in"
)
def test_deployed_image_maintenance_uses_only_closed_diagnostics():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "maintenance_privacy_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "maintenance_privacy_failed"
    assert report == {
        "status": "passed",
        "checks": {
            "maintenance_redacted": True,
            "cleanup_redacted": True,
            "retry_survived": True,
        },
    }
