"""Opt-in isolated Redis fixture; no provider invocation or business writes."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,sys,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
import redis.asyncio as aioredis
from service.settings import config
from service.infrastructure.document_audit import registry as module
assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==json.load(sys.stdin)
stage='connection'
async def main():
 global stage
 first=aioredis.from_url(config.redis.dsn,decode_responses=True,
   socket_connect_timeout=2,socket_timeout=2)
 second=aioredis.from_url(config.redis.dsn,decode_responses=True,
   socket_connect_timeout=2,socket_timeout=2)
 attempt=str(uuid.uuid4()); scope=hashlib.sha256(('fixture:'+attempt).encode()).hexdigest()
 producer=module.AuditProducerRegistry(first,attempt_id=attempt,scope_digest=scope)
 try:
  stage='claim'
  assert await producer.claim(fresh_attempt=True)
  payload={'schema_version':1,'attempt_id':attempt,'revision':1,'receipts':[{
   'receipt_id':'fixture-call','provider':'gigachat','model':'GigaChat-2-Max',
   'kind':'document_visual_audit','prompt':30,'completion':3,'estimated':False}]}
  await producer.checkpoint(payload)
  stage='reconnect'
  reader=module.AuditProducerRegistry(second,attempt_id=attempt,scope_digest=scope)
  assert (await reader.snapshot())['checkpoint']==payload
  assert not await reader.claim(fresh_attempt=True)
  stage='seal'
  result={'status':'failed','passed':False,'retryable':False}
  await producer.seal(result)
  assert await reader.snapshot()=={'state':'terminal','checkpoint':payload,'result':result}
  await producer.seal(result)
  try:
   await reader.seal(result)
  except module.AuditRegistryUnavailable:
   pass
  else:
   raise AssertionError('reader_cannot_finalize_producer')
  stage='cleanup'
 finally:
  raw=await first.get(producer.key)
  if raw is not None:
   value=json.loads(raw)
   assert value['attempt_id']==attempt and value['scope_digest']==scope
   assert await first.delete(producer.key)==1
  assert await second.get(producer.key) is None
  await first.aclose(); await second.aclose()
 print(json.dumps({'status':'passed','retained':True,'sealed':True,'removed':True}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(os.getenv("S37_LIVE_AUDIT_REGISTRY") != "1", reason="opt-in isolated dev Redis")
def test_actual_redis_retains_checkpoint_and_explicit_completion_across_clients():
    source = Path("service/infrastructure/document_audit/registry.py")
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-c", _PROBE],
        input=json.dumps(hashlib.sha256(source.read_bytes()).hexdigest()).encode(),
        capture_output=True,
        timeout=30,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "audit_registry_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "audit_registry_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report == {"status": "passed", "retained": True, "sealed": True, "removed": True}
