"""Opt-in isolated Uvicorn transport probe; no shared runtime fault injection."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,socket,sys,urllib.request,urllib.error
sys.path.insert(0,'/opt/workspace-sidecar/service')
import presentation.http as http
from fastapi import FastAPI
from drivers.base import DriverError
import uvicorn
assert hashlib.sha256(SOURCE.encode()).hexdigest()==DIGEST
exec(compile(SOURCE,http.__file__,'exec'),http.__dict__)
class Capture(logging.Handler):
 def __init__(self): super().__init__(); self.records=[]
 def emit(self,record): self.records.append(record)
async def main():
 marker='synthetic-private-driver-body'
 fixture=FastAPI(); fixture.exception_handlers.update(http.app.exception_handlers)
 @fixture.get('/failure')
 async def failure(): raise DriverError(marker)
 sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
 server=uvicorn.Server(uvicorn.Config(fixture,log_config=None,log_level='warning',
  access_log=False,lifespan='off'))
 capture=Capture(); loggers=[logging.getLogger(name) for name in ('workspace-sidecar','uvicorn.error')]
 previous=[(log.level,log.propagate) for log in loggers]
 for log in loggers: log.addHandler(capture); log.setLevel(logging.WARNING); log.propagate=False
 task=asyncio.create_task(server.serve(sockets=[sock]))
 try:
  async with asyncio.timeout(5):
   while not server.started:
    if task.done(): raise AssertionError('server_stopped')
    await asyncio.sleep(0.01)
  def request():
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/failure',timeout=5):
     raise AssertionError('failure_accepted')
   except urllib.error.HTTPError as error:
    code=error.code; raw=error.read(4097); error.close()
    assert len(raw)<=4096
    return code,raw
  code,raw=await asyncio.to_thread(request)
  assert code==502 and json.loads(raw)=={'error':'driver_failed','detail':'workspace driver failed'}
  assert marker not in raw.decode()
  assert len(capture.records)==1
  record=capture.records[0]
  assert record.failure_code=='driver_failed' and record.component=='workspace_driver'
  assert record.exc_info is None and marker not in record.getMessage()
  return {'http_502':True,'bounded_response':True,'bounded_log':True,'no_traceback':True,
   'source_parity':True}
 finally:
  server.should_exit=True
  await asyncio.wait_for(task,5)
  sock.close()
  for log,(level,propagate) in zip(loggers,previous):
   log.removeHandler(capture); log.setLevel(level); log.propagate=propagate
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except BaseException:
 print(json.dumps({'status':'failed','stage':'driver_http_privacy'})); raise SystemExit(1)
"""


def test_driver_transport_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DRIVER_HTTP_PRIVACY") != "1", reason="isolated Uvicorn privacy acceptance"
)
def test_actual_http_driver_failure_has_no_private_body_or_traceback():
    source = (Path(__file__).parents[1] / "service/presentation/http.py").read_text(
        encoding="utf-8"
    )
    header = f"SOURCE={source!r}\nDIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + _PROBE).encode(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "driver_http_privacy_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "driver_http_privacy_failed"
    assert report == {
        "status": "passed",
        "checks": {
            "http_502": True,
            "bounded_response": True,
            "bounded_log": True,
            "no_traceback": True,
            "source_parity": True,
        },
    }
