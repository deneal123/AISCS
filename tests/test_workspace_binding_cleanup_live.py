"""Opt-in real Redis proof; only a fresh, expiring synthetic key is touched."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,sys,uuid
from pathlib import Path
logging.disable(logging.CRITICAL)
from service.settings import Config
from service.infrastructure.cache.manager import RedisManager
from service.infrastructure import workspace_client as wc
async def main():
 expected=json.load(sys.stdin)['source_digest']
 assert hashlib.sha256(Path(wc.__file__).read_bytes()).hexdigest()==expected
 manager=RedisManager(Config().redis); redis=manager.get_client()
 key='acceptance:workspace-cleanup:'+uuid.uuid4().hex
 cases=0
 try:
  # A replacement published while the old DELETE was in flight must survive.
  newer=json.dumps({'workspace_id':'new-generation','user_id':'synthetic-owner'})
  assert await redis.set(key,newer,nx=True,ex=60)
  assert await wc._redis_call(redis,'eval',wc._FORGET_DESTROYED_BINDING,
   1,key,'old-generation')==0
  assert await redis.get(key)==newer; cases+=1
  assert await wc._redis_call(redis,'eval',wc._FORGET_DESTROYED_BINDING,
   1,key,'new-generation')==1
  assert await redis.get(key) is None; cases+=1
  assert await wc._redis_call(redis,'eval',wc._FORGET_DESTROYED_BINDING,
   1,key,'new-generation')==1; cases+=1
  for corrupt in ('not-json','null','[]','42','{"user_id":"synthetic-owner"}'):
   await redis.set(key,corrupt,ex=60)
   assert await wc._redis_call(redis,'eval',wc._FORGET_DESTROYED_BINDING,
    1,key,'old-generation')==0
   assert await redis.get(key)==corrupt; cases+=1
 finally:
  await redis.delete(key)
  assert await redis.exists(key)==0
  await manager.close()
 print(json.dumps({'cases':cases,'fixture_removed':True}))
try:
 asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','stage':'binding_cleanup'}))
 raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_BINDING_CLEANUP") != "1",
    reason="explicit isolated Redis cleanup acceptance",
)
def test_binding_compare_delete_preserves_replacement_and_corrupt_records():
    source = Path(__file__).resolve().parents[1] / "service/infrastructure/workspace_client.py"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps({"source_digest": hashlib.sha256(source.read_bytes()).hexdigest()}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "binding_cleanup_probe_failed"
    assert json.loads(result.stdout) == {"cases": 8, "fixture_removed": True}
