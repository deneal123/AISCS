"""Opt-in PostgreSQL contention and isolated holder-process death acceptance."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,inspect,json,logging,subprocess,sys,time,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
from sqlalchemy import text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_job_execution
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_execution_session
from service.services.chat.infrastructure.chat_worker.execution.watchdog import (
 run_with_execution_ownership)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
stage='freshness'
child=None
async def main():
 global stage,child
 source=Path(inspect.getfile(inspect.unwrap(claim_job_execution))).read_bytes()
 assert hashlib.sha256(source).hexdigest()=='__DIGEST__'
 watchdog=Path(inspect.getfile(run_with_execution_ownership)).read_bytes()
 assert hashlib.sha256(watchdog).hexdigest()=='__WATCHDOG_DIGEST__'
 connector=PgConnector(config.pg)
 identity=str(uuid.uuid4())
 try:
  stage='contention'
  async with claim_job_execution(connector,identity) as first:
   assert first
   async with connector.get_session_context() as transaction:
    assert await transaction.scalar(text('SELECT 1'))==1
    await transaction.commit()
   async with claim_job_execution(connector,identity) as second:
    assert second is False
  stage='release'
  async with claim_job_execution(connector,identity) as held: assert held
  stage='body_failure'
  try:
   async with claim_job_execution(connector,identity) as held:
    assert held
    raise RuntimeError('synthetic')
  except RuntimeError: pass
  async with claim_job_execution(connector,identity) as held: assert held
  stage='process_holder'
  code='''
import asyncio,hashlib,inspect,json,logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_job_execution
async def main():
 source=Path(inspect.getfile(inspect.unwrap(claim_job_execution))).read_bytes()
 assert hashlib.sha256(source).hexdigest()=='__DIGEST__'
 connector=PgConnector(config.pg)
 async with claim_job_execution(connector,'__JOB__') as held:
  assert held
  print(json.dumps({'status':'held'}),flush=True)
  await asyncio.Event().wait()
try: asyncio.run(main())
except Exception: print(json.dumps({'status':'failed'}),flush=True)
'''.replace('__JOB__',identity)
  child=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,
   stderr=subprocess.PIPE,text=True)
  line=await asyncio.wait_for(asyncio.to_thread(child.stdout.readline),timeout=10)
  assert json.loads(line)=={'status':'held'}
  async with claim_job_execution(connector,identity) as held: assert held is False
  stage='process_death'
  child.kill()
  await asyncio.to_thread(child.wait,timeout=5)
  stage='death_release'
  released=False
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   async with claim_job_execution(connector,identity) as held:
    if held:
     released=True
     break
   await asyncio.sleep(0.05)
  assert released
  stage='connection_loss'
  started=asyncio.Event(); stopped=asyncio.Event()
  async def operation():
   started.set()
   try: await asyncio.Event().wait()
   finally: stopped.set()
  async with claim_execution_session(connector,identity) as lease:
   assert lease is not None
   pid=await lease.scalar(text('SELECT pg_backend_pid()'))
   assert type(pid) is int and pid>0
   task=asyncio.create_task(run_with_execution_ownership(lease,identity,operation))
   try:
    await asyncio.wait_for(started.wait(),timeout=5)
    async with connector.get_session_context() as control:
     assert await control.scalar(text('SELECT pg_terminate_backend(:pid)'),{'pid':pid}) is True
    try:
     await asyncio.wait_for(task,timeout=5)
     raise AssertionError('ownership loss not detected')
    except JobStateUnavailable: pass
    assert stopped.is_set()
   finally:
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
  stage='loss_reacquisition'
  async with claim_job_execution(connector,identity) as held: assert held
 finally:
  if child is not None:
   if child.poll() is None:
    child.kill()
    await asyncio.to_thread(child.wait,timeout=5)
   child.stdout.close()
   child.stderr.close()
  await connector.close()
try:
 asyncio.run(main())
 print(json.dumps({'status':'passed','contention':True,'process_death_release':True,'connection_loss_cancelled':True}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage}))
 raise SystemExit(1)
"""


def _probe_sources():
    source = Path("service/services/chat/infrastructure/chat_worker/execution/lease.py")
    watchdog = source.with_name("watchdog.py")
    return source, watchdog


def test_execution_lease_probe_is_valid_python():
    ast.parse(_PROBE)
    assert all(path.is_file() for path in _probe_sources())


@pytest.mark.skipif(os.getenv("S37_LIVE_EXECUTION_LEASE") != "1", reason="opt-in dev PostgreSQL")
def test_dev_execution_lease_contention_and_holder_death():
    source, watchdog = _probe_sources()
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "docker/.env.dev",
            "-f",
            "docker/docker-compose.dev.yaml",
            "--profile",
            "dev",
            "--profile",
            "celery",
            "exec",
            "-T",
            "backend",
            "python",
            "-",
        ],
        input=_PROBE.replace("__DIGEST__", hashlib.sha256(source.read_bytes()).hexdigest())
        .replace("__WATCHDOG_DIGEST__", hashlib.sha256(watchdog.read_bytes()).hexdigest())
        .encode(),
        capture_output=True,
        cwd="..",
        timeout=40,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "execution_lease_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "execution_lease_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["contention"] and report["process_death_release"]
    assert report["connection_loss_cancelled"]
