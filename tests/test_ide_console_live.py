"""Opt-in real non-root isolated execution; never use a user's project container."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

PROBE = r"""
import asyncio,hashlib,json,sys,uuid
sys.path.insert(0,'/opt/workspace-sidecar/service')
import drivers.docker_cli as module
from domain.policy import WorkspacePolicy
assert hashlib.sha256(SOURCE.encode()).hexdigest()==DIGEST
exec(compile(SOURCE,module.__file__,'exec'),module.__dict__)
native_argv=module._create_argv
def isolated_argv(*args,**kwargs):
 return ['gpthub.workspace=0' if arg=='gpthub.workspace=1' else arg
  for arg in native_argv(*args,**kwargs)]
module._create_argv=isolated_argv
async def main():
 driver=module.DockerCliDriver(); ref=None
 try:
  policy=WorkspacePolicy()
  ref=await driver.create(str(uuid.uuid4()),policy)
  await driver.verify_isolation(ref,policy)
  result=await driver.exec(ref,"python3 -c 'print(\"Hello, world!\")'",timeout_sec=10,max_output_chars=200)
  assert result.exit_code==0 and result.stdout=='Hello, world!\n' and not result.stderr
  assert not result.timed_out and not result.truncated
  result=await driver.exec(ref,"printf 'failure' >&2; exit 7",timeout_sec=5,max_output_chars=200)
  assert result.exit_code==7 and result.stderr=='failure'
  result=await driver.exec(ref,"printf '1234567890'",timeout_sec=5,max_output_chars=5)
  assert result.truncated and result.stdout.startswith('12345')
  result=await driver.exec(ref,"sleep 20",timeout_sec=1,max_output_chars=200)
  assert result.timed_out and result.exit_code!=0
  return {'stdout':True,'stderr_exit':True,'truncation':True,'timeout':True,'isolation':True}
 finally:
  if ref is not None:
   await driver.destroy(ref)
   code,remaining,_=await module._docker('ps','-aq','--no-trunc','--filter',f'id={ref.container_id}')
   assert code==0 and not remaining.strip()
try:
 checks=asyncio.run(main())
 print(json.dumps({'passed':checks,'fixture_deleted':True}))
except BaseException as error:
 print(json.dumps({'failed':type(error).__name__})); raise SystemExit(1)
"""


def test_console_probe_syntax():
    ast.parse(PROBE)


@pytest.mark.skipif(os.getenv("IDE_CONSOLE_LIVE") != "1", reason="owned isolated Docker probe")
def test_console_native_stdout_stderr_timeout_and_cleanup():
    source = (Path(__file__).parents[1] / "service/drivers/docker_cli.py").read_text(
        encoding="utf-8"
    )
    header = f"SOURCE={source!r}\nDIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + PROBE).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "console_probe_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, report
    assert report == {
        "passed": {
            "stdout": True,
            "stderr_exit": True,
            "truncation": True,
            "timeout": True,
            "isolation": True,
        },
        "fixture_deleted": True,
    }
