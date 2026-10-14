"""Opt-in owned sandbox probe: cancellation must stop the in-container process group."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,sys,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
import drivers.docker_cli as module
from domain.policy import WorkspacePolicy
assert hashlib.sha256(SOURCE.encode()).hexdigest()==DIGEST
exec(compile(SOURCE,module.__file__,'exec'),module.__dict__)
STAGE='create'
native_argv=module._create_argv
def isolated_argv(*args,**kwargs):
 # The shared reaper must not adopt this unsigned test-only container.
 return ['gpthub.workspace=0' if arg=='gpthub.workspace=1' else arg
  for arg in native_argv(*args,**kwargs)]
module._create_argv=isolated_argv
async def main():
 global STAGE
 driver=module.DockerCliDriver(); ref=None; task=None
 try:
  ref=await driver.create(str(uuid.uuid4()),WorkspacePolicy())
  STAGE='isolation'
  await driver.verify_isolation(ref,WorkspacePolicy())
  STAGE='command_start'
  task=asyncio.create_task(driver.exec(ref,'sleep 60',timeout_sec=65,max_output_chars=100))
  async with asyncio.timeout(10):
   while True:
    code,raw,_=await module._docker('exec',ref.container_id,'cat',module._PGID_FILE)
    if code==0 and raw.strip().isdigit():
     ready,_,_=await module._docker('exec',ref.container_id,'/bin/sh','-c',
      'pgid=$(cat /tmp/.ws-exec.pgid); kill -0 -"$pgid" 2>/dev/null')
     if ready==0: break
    assert not task.done()
    await asyncio.sleep(0.05)
  task.cancel()
  STAGE='cancel_settlement'
  try: await asyncio.wait_for(task,20)
  except asyncio.CancelledError: pass
  else: raise AssertionError('cancellation_lost')
  STAGE='group_absence'
  script='pgid=$(cat /tmp/.ws-exec.pgid); kill -0 -"$pgid" 2>/dev/null'
  async with asyncio.timeout(3):
   for _ in range(10):
    code,_,_=await module._docker('exec',ref.container_id,'/bin/sh','-c',script)
    if code==1: break
    await asyncio.sleep(0.05)
  if code!=1:
   inspect_code,listing,_=await module._docker('exec',ref.container_id,'/bin/sh','-c',
    'for f in /proc/[0-9]*/stat; do [ -r "$f" ] && cat "$f"; done; exit 0')
   assert inspect_code==0
   records=[line.rsplit(') ',1)[1].split() for line in listing.splitlines() if ') ' in line]
   states=[record[0] for record in records if len(record)>2 and record[2]==raw.strip()]
   STAGE='group_zombie_only' if states and all(s.startswith('Z') for s in states) else 'group_live'
   raise AssertionError('group_survived_cancel')
  return {'source_parity':True,'cancel_preserved':True,'group_absent':True}
 finally:
  if task is not None and not task.done():
   task.cancel(); await asyncio.gather(task,return_exceptions=True)
  if ref is not None:
   await driver.destroy(ref)
   code,remaining,_=await module._docker('ps','-aq','--no-trunc','--filter',
    f'id={ref.container_id}')
   assert code==0 and not remaining.strip(), 'fixture_cleanup_incomplete'
try:
 checks=asyncio.run(main())
 print(json.dumps({'status':'passed','checks':checks,'owned_fixture_deleted':True}))
except BaseException as error:
 reason='timeout' if isinstance(error,TimeoutError) else 'assertion' if isinstance(error,AssertionError) else 'driver' if isinstance(error,module.DriverError) else 'internal'
 print(json.dumps({'status':'failed','stage':STAGE,'reason':reason})); raise SystemExit(1)
"""


def test_exec_cancellation_probe_parses():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_EXEC_CANCELLATION") != "1", reason="isolated owned Docker cancellation"
)
def test_exec_cancellation_stops_real_container_process_group():
    source = (Path(__file__).parents[1] / "service/drivers/docker_cli.py").read_text(
        encoding="utf-8"
    )
    header = f"SOURCE={source!r}\nDIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + _PROBE).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "exec_cancellation_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, (
        f"exec_cancellation_{report.get('stage', 'unknown')}_{report.get('reason', 'unknown')}"
    )
    assert report == {
        "status": "passed",
        "checks": {"source_parity": True, "cancel_preserved": True, "group_absent": True},
        "owned_fixture_deleted": True,
    }
