"""Kill only a child PID created by this probe, never a serving/shared process."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,os,select,signal,sys,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
import redis.asyncio as aioredis
from service.settings import config
from service.infrastructure.document_audit import registry as registry_module
from service.infrastructure.document_audit import process as process_module
expected=json.load(sys.stdin)
assert [hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
 for m in (registry_module,process_module)]==expected['hashes']
attempt=str(uuid.uuid4()); scope=hashlib.sha256(('fixture:'+attempt).encode()).hexdigest()
rd,wr=os.pipe(); pid=os.fork(); reaped=False
async def produce():
 client=aioredis.from_url(config.redis.dsn,decode_responses=True,
   socket_connect_timeout=2,socket_timeout=2)
 registry=registry_module.AuditProducerRegistry(client,attempt_id=attempt,scope_digest=scope)
 assert await registry.claim(fresh_attempt=True)
 await registry.checkpoint({'schema_version':1,'attempt_id':attempt,'revision':1,'receipts':[{
  'receipt_id':'fixture-call','provider':'gigachat','model':'GigaChat-2-Max',
  'kind':'document_visual_audit','prompt':30,'completion':3,'estimated':False}]})
 if expected['sealed']:
  await registry.seal({'status':'failed','passed':False,'retryable':False})
 os.write(wr,b'ready')
 await asyncio.Event().wait()
if pid==0:
 os.close(rd)
 try: asyncio.run(produce())
 finally: os._exit(77)
os.close(wr)
async def verify(killed):
 client=aioredis.from_url(config.redis.dsn,decode_responses=True,
   socket_connect_timeout=2,socket_timeout=2)
 registry=registry_module.AuditProducerRegistry(client,attempt_id=attempt,scope_digest=scope)
 try:
  snapshot=await registry.snapshot()
  if killed or expected['sealed']:
   assert snapshot['state']=='terminal'
   assert snapshot['result']['status']==('failed' if expected['sealed'] else 'internal')
  else:
   assert snapshot['state']=='active'
  assert snapshot['checkpoint']['receipts'][0]['prompt']==30
  assert not await registry.claim(fresh_attempt=True)
  assert 'owner' not in snapshot and 'producer_token' not in snapshot
 finally:
  if killed:
   stored=await registry.read(); assert stored['attempt_id']==attempt and stored['scope_digest']==scope
   assert await client.delete(registry.key)==1
   assert await registry.read() is None
  await client.aclose()
try:
 assert pid>1 and pid!=os.getpid()
 assert select.select([rd],[],[],12)[0] and os.read(rd,32)==b'ready'
 asyncio.run(verify(False))
 os.kill(pid,signal.SIGKILL); actual,status=os.waitpid(pid,0); reaped=True
 assert actual==pid and os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
 asyncio.run(verify(True))
 print(json.dumps({'status':'passed','sigkill':True,'receipt_retained':True,'removed':True}))
except BaseException:
 print(json.dumps({'status':'failed'})); raise SystemExit(1)
finally:
 os.close(rd)
 if not reaped:
  waited,status=os.waitpid(pid,os.WNOHANG)
  if waited==0: os.kill(pid,signal.SIGKILL); os.waitpid(pid,0)
  try: asyncio.run(verify(True))
  except Exception: pass
"""


def test_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_AUDIT_SIGKILL") != "1", reason="opt-in owned Linux child/Redis"
)
@pytest.mark.parametrize("sealed", [False, True])
def test_actual_child_sigkill_retains_receipt_without_reinvocation(sealed):
    names = ("document_audit_registry.py", "document_audit_process.py")
    base = Path("service/infrastructure")
    hashes = [hashlib.sha256((base / name).read_bytes()).hexdigest() for name in names]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-c", _PROBE],
        input=json.dumps({"hashes": hashes, "sealed": sealed}).encode(),
        capture_output=True,
        timeout=35,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert result.returncode == 0 and lines, "owned_producer_sigkill_probe_failed"
    assert json.loads(lines[-1]) == {
        "status": "passed",
        "sigkill": True,
        "receipt_retained": True,
        "removed": True,
    }
