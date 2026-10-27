"""Opt-in dev Redis proof with exact temporary keys; no providers or billing."""

import ast
import asyncio
import json
import os
import subprocess

import pytest

PROBE = """
import asyncio,json,logging,uuid
from unittest.mock import AsyncMock,patch
from service.settings import Config
from service.infrastructure.cache.manager import RedisManager, call_redis
from service.services.chat.infrastructure import agent_context as context
from service.services.chat.infrastructure.chat_worker.factory import ChatWorkerDependencyFactory
logging.disable(logging.CRITICAL)
stage='prepare'
async def main():
 global stage
 config=Config()
 manager=RedisManager(config.redis)
 clients=[ChatWorkerDependencyFactory().create_redis_client(config),manager.get_client()]
 completed=0
 for client in clients:
  thread='s37-references-'+uuid.uuid4().hex
  keys=[f'chat:{thread}:file_ids',f'chat:{thread}:repo_graphs']
  try:
   stage='persist'
   assert await context._recall_or_persist_thread_tabular(
    client,thread,['fixture-file'],has_new_file=True)==['fixture-file']
   assert 0<await call_redis(client,'ttl',keys[0])<=7200
   stage='recall'
   assert await context._recall_or_persist_thread_tabular(client,thread,[])==['fixture-file']
   stage='repository_read'
   await call_redis(client,'lpush',keys[1],'fixture-repository')
   await call_redis(client,'expire',keys[1],120)
   assert await context.read_thread_repo_graphs(client,thread)==['fixture-repository']
   stage='detach'
   with patch.object(context,'recall_last_thread_image_url',AsyncMock(return_value=None)):
    assert await context.collect_message_extras(client,thread,[],detach_files=True)==(None,False,[])
   assert await call_redis(client,'exists',keys[1])==0
   stage='forget'
   await context._forget_thread_files(client,thread)
   assert await call_redis(client,'exists',keys[0])==0
   completed+=1
  finally:
   stage='cleanup'
   await call_redis(client,'delete',*keys)
   assert await call_redis(client,'exists',*keys)==0
 await asyncio.to_thread(clients[0].close)
 await clients[1].aclose()
 return {'clients':completed,'commands_awaited':True,'exact_cleanup':True,'model_calls':0}
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main())}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage}));raise SystemExit(1)
"""


def test_reference_probe_is_valid_python():
    ast.parse(PROBE)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_ATTACHMENT_REFERENCES") != "1", reason="dev Redis acceptance"
)
async def test_sync_and_async_redis_reference_lifecycle():
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=PROBE.encode(),
        capture_output=True,
        timeout=45,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "bounded reference report missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, (
        f"reference acceptance failed at {report.get('stage', 'unknown')}"
    )
    assert report == {
        "status": "passed",
        "checks": {"clients": 2, "commands_awaited": True, "exact_cleanup": True, "model_calls": 0},
    }
