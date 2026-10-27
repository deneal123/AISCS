"""Opt-in serving metadata scans over owned fixtures, not user Library rows."""

import json
import os
import subprocess

import pytest

PROBE = r"""
import asyncio,hashlib,json,logging,uuid
from service.composition.storage import build_file_storage
from service.infrastructure.cache.manager import RedisManager
from service.services.files.infrastructure.scan_queue import DurableScanQueue,ScanClaim
from service.settings import Config
logging.disable(logging.CRITICAL)

async def main():
 config=Config();storage=build_file_storage(config)
 redis=RedisManager(config.redis).get_client()
 queue=DurableScanQueue(redis)
 key=storage.build_file_path('s37-scan-acceptance','CHAT',uuid.uuid4().hex+'.txt')
 output='file:'+key+':stream'
 body=b'owned synthetic serving scan fixture'
 try:
  assert await redis.llen(queue.source)==0
  if await redis.exists(queue.stream):assert await redis.xlen(queue.stream)==0
  await storage.upload_file(file_key=key,file_data=body)
  await redis.rpush(queue.source,key)
  deadline=asyncio.get_running_loop().time()+30
  while True:
   entries=await redis.xrange(output,count=2) if await redis.exists(output) else []
   if entries:break
   if asyncio.get_running_loop().time()>=deadline:raise TimeoutError('fixture_scan_timeout')
   await asyncio.sleep(0.1)
  assert len(entries)==1
  fields=entries[0][1];data=fields.get('data',fields.get(b'data'))
  payload=json.loads(data)
  assert payload=={'event':'scanned','file_key':key,'result':{
   'status':'ok','size':len(body),'sha256':hashlib.sha256(body).hexdigest()}}
  assert await redis.llen(queue.source)==0 and await redis.xlen(queue.stream)==0
  assert (await redis.xpending(queue.stream,queue.group))['pending']==0
 finally:
  # Only the exact fixture may be removed/reclaimed if observation fails.
  await redis.lrem(queue.source,1,key)
  if await redis.exists(queue.stream):
   for entry_id,fields in await redis.xrange(queue.stream,count=100):
    encoded=fields.get('file_key_hex',fields.get(b'file_key_hex'))
    if encoded is None:continue
    try:value=bytes.fromhex(encoded.decode() if isinstance(encoded,bytes) else encoded).decode()
    except (ValueError,UnicodeError):continue
    if value!=key:continue
    await redis.xclaim(queue.stream,queue.group,queue.consumer,0,[entry_id],justid=True)
    pending=await redis.xpending_range(queue.stream,queue.group,entry_id,entry_id,1)
    if pending:
     claim=ScanClaim(entry_id,key,queue.consumer,pending[0]['times_delivered'])
     assert await queue.publish(claim,output,json.dumps({'event':'scanned','file_key':key,
       'result':{'status':'error','reason':'unavailable'}}))
  await storage.delete_file(file_key=key)
  from minio.error import S3Error
  try:
   await asyncio.to_thread(storage._client.stat_object,storage._bucket,key)
  except S3Error as missing:
   assert missing.code=='NoSuchKey'
  else:raise AssertionError('fixture_cleanup_failed')
  await redis.delete(output)
  await redis.aclose()
 return {'status':'passed','serving_loop':True,'exact_digest':True,
         'single_result':True,'fixture_cleaned':True,'user_file_rows':0,'provider_calls':0}

try:print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':'serving_scan_fixture'}));raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_SERVING_SCAN") != "1", reason="owned dev storage/queue fixture opt-in"
)
@pytest.mark.parametrize("copies", [0, 1, 100_000], ids=["empty", "tiny", "multi-chunk"])
def test_serving_loop_scans_owned_fixture_and_commits_one_matching_result(copies):
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=PROBE.replace(
            "body=b'owned synthetic serving scan fixture'",
            f"body=b'owned synthetic serving scan fixture'*{copies}",
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, "serving_scan_fixture_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "serving_loop": True,
        "exact_digest": True,
        "single_result": True,
        "fixture_cleaned": True,
        "user_file_rows": 0,
        "provider_calls": 0,
    }
