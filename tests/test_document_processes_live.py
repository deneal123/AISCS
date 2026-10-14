"""Opt-in installed dev command boundary; no compiler or paid model job."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_document_processes import _PIPE_PROBE

_PROBE = """
import asyncio,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/opt/workspace-sidecar/service')
from infrastructure import document_processes as processes,document_compiler as compiler
expected=json.load(sys.stdin)
stage='source'
async def main():
 global stage
 for module in (processes,compiler):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected[module.__name__]
 original=asyncio.create_subprocess_exec
 children=[]
 async def spawn(*args,**kwargs):
  child=await original(*args,**kwargs);children.append(child);return child
 processes.asyncio.create_subprocess_exec=spawn
 try:
  for stream in ('stdout','stderr'):
   stage=stream
   script=f"import sys;sys.{stream}.buffer.write(b'x'*(2*1024*1024))"
   try: await processes.command(sys.executable,'-c',script,timeout=5)
   except processes.CommandOutputLimit as error: assert str(error)=='compiler_output_too_large'
   else: raise AssertionError
   assert children[-1].returncode is not None
  stage='compiler_mapping'
  try: await compiler._command(sys.executable,'-c',script,timeout=5)
  except compiler.CompilerFailure as error: assert error.code=='runtime_unavailable'
  else: raise AssertionError
  stage='timeout'
  try: await processes.command(sys.executable,'-c','import time;time.sleep(30)',timeout=.05)
  except TimeoutError: pass
  else: raise AssertionError
  assert len(children)==4 and all(child.returncode is not None for child in children)
  return {'source_matches':True,'streams_bounded':True,'safe_mapping':True,'children_reaped':4}
 finally:
  processes.asyncio.create_subprocess_exec=original
  for child in children:
   if child.returncode is None:
    child.kill();await child.wait()
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_COMMAND") != "1", reason="opt-in installed command probe"
)
def test_installed_command_output_budget_and_cleanup():
    service = Path(__file__).resolve().parents[1] / "service"
    expected = {
        f"infrastructure.{name}": hashlib.sha256(
            (service / "infrastructure" / f"{name}.py").read_bytes()
        ).hexdigest()
        for name in ("document_processes", "document_compiler")
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps(expected),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "installed_command_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "checks": {
            "source_matches": True,
            "streams_bounded": True,
            "safe_mapping": True,
            "children_reaped": 4,
        },
    }


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_COMMAND") != "1", reason="opt-in installed pipe probe"
)
@pytest.mark.parametrize("mode", ["reject", "timeout", "cancel"])
def test_installed_pipe_backpressure_cleanup(mode):
    source = Path(__file__).resolve().parents[1] / "service/infrastructure/document_processes.py"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    wrapper = """
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/opt/workspace-sidecar/service')
from infrastructure import document_processes
data=json.load(sys.stdin)
try:
 assert hashlib.sha256(Path(document_processes.__file__).read_bytes()).hexdigest()==data['digest']
 sys.argv=['probe','/opt/workspace-sidecar/service',data['mode']]
 exec(data['probe'])
except BaseException:
 print(json.dumps({'status':'failed'}));sys.exit(1)
"""
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", wrapper],
        input=json.dumps({"probe": _PIPE_PROBE, "digest": expected, "mode": mode}),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, "installed_pipe_probe_failed"
    assert json.loads(result.stdout) == {"status": "passed", "reaped": 2}
