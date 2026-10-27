"""Opt-in dev Redis probe; no provider, billing, or service restart."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,inspect,json,logging,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
from service.settings import config
from service.services.chat.infrastructure.chat_worker.factory import ChatWorkerDependencyFactory
from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
 CancelledByUser,run_with_cancel)
stage='source_freshness'
async def main():
 global stage
 assert hashlib.sha256(Path(inspect.getfile(run_with_cancel)).read_bytes()).hexdigest()==(
  '__DIGEST__')
 factory_source=Path(inspect.getfile(ChatWorkerDependencyFactory)).read_bytes()
 assert hashlib.sha256(factory_source).hexdigest()==(
  '__FACTORY_DIGEST__')
 client=ChatWorkerDependencyFactory().create_redis_client(config)
 assert client is not None
 assert client.connection_pool.connection_kwargs['socket_timeout']==2
 assert client.connection_pool.connection_kwargs['socket_connect_timeout']==2
 identity='s37-cancel-watch-'+uuid.uuid4().hex
 key='chat:cancel:'+identity
 cleaned=asyncio.Event()
 class Transient:
  calls=0
  def get(self,requested):
   assert requested==key
   self.calls+=1
   if self.calls==1: raise RuntimeError('private-redis-marker')
   return client.get(requested)
  def delete(self,requested):
   assert requested==key
   return client.delete(requested)
 async def work():
  try: await asyncio.Event().wait()
  finally: cleaned.set()
 try:
  stage='fixture'
  assert client.set(key,'1',ex=30,nx=True)
  stage='watcher'
  control=Transient()
  try:
   await asyncio.wait_for(run_with_cancel(work(),redis_client=control,
    celery_task_id=identity,poll_interval=0.01),timeout=5)
  except CancelledByUser: pass
  else: raise AssertionError('cancel_not_observed')
  assert cleaned.is_set() and control.calls>=2
  assert client.get(key) is None
 finally:
  client.delete(key)
  client.close()
try:
 asyncio.run(main())
 print(json.dumps({'status':'passed','watcher_recovered':True,'fixture_cleaned':True}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage}))
 raise SystemExit(1)
"""


def test_cancel_watcher_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(os.getenv("S37_LIVE_CANCEL_WATCHER") != "1", reason="opt-in dev Redis probe")
def test_dev_redis_cancel_after_transient_observation_failure():
    source = Path("service/services/chat/infrastructure/chat_worker/execution/cancellation.py")
    probe = _PROBE.replace("__DIGEST__", hashlib.sha256(source.read_bytes()).hexdigest())
    probe = probe.replace(
        "__FACTORY_DIGEST__",
        hashlib.sha256(
            Path("service/services/chat/infrastructure/chat_worker/factory.py").read_bytes()
        ).hexdigest(),
    )
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
        input=probe.encode(),
        capture_output=True,
        cwd="..",
        timeout=30,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "cancel_watcher_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "cancel_watcher_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["watcher_recovered"] and report["fixture_cleaned"]
