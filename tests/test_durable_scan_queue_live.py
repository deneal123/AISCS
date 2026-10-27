"""Opt-in isolated Redis claim corpus; never touches the serving scan queue."""

import json
import os
import subprocess

import pytest

PROBE = r"""
import asyncio,json,uuid
from redis.exceptions import ResponseError
from service.infrastructure.cache.manager import RedisManager
from service.services.files.infrastructure.scan_queue import DurableScanQueue,SCAN_LEASE_MS
from service.settings import Config

async def main():
 redis=RedisManager(Config().redis).get_client()
 prefix='file:scan:acceptance:'+uuid.uuid4().hex
 first=DurableScanQueue(redis,namespace=prefix)
 second=DurableScanQueue(redis,namespace=prefix)
 invalid=DurableScanQueue(redis,namespace=prefix+':invalid')
 output=prefix+':result'
 broken=prefix+':broken'
 keys=[first.source,first.stream,invalid.source,invalid.stream,output,broken]
 assert all(key.startswith(prefix+':') for key in keys)
 cases=0
 try:
  await redis.rpush(first.source,'fixture-first','fixture-second')
  await first.transfer_one()
  remaining=await redis.lrange(first.source,0,-1)
  assert remaining in (['fixture-second'],[b'fixture-second']);cases+=1
  a=await first.claim()
  b=await second.claim()
  assert a.file_key=='fixture-first' and b.file_key=='fixture-second';cases+=1
  assert await first.claim() is None;cases+=1
  assert await first.renew(a)
  pending=await redis.xpending_range(first.stream,first.group,a.entry_id,a.entry_id,1)
  assert pending[0]['times_delivered']==a.attempt;cases+=1
  await redis.xclaim(first.stream,first.group,first.consumer,0,[a.entry_id],
                    idle=SCAN_LEASE_MS+1,justid=True)
  assert not await first.renew(a);cases+=1
  assert not await first.publish(a,output,'fixture');cases+=1
  replacement=await second.claim()
  assert replacement.entry_id==a.entry_id and replacement.attempt==2;cases+=1
  assert not await first.publish(a,output,'obsolete')
  assert not await first.renew(a);cases+=1
  assert await second.publish(replacement,output,'fixture')
  assert not await second.publish(replacement,output,'replay')
  assert await redis.xlen(output)==1;cases+=1
  await redis.set(broken,'wrong-type')
  try:await second.publish(b,broken,'fixture')
  except ResponseError:pass
  else:raise AssertionError('wrong_type_accepted')
  pending=await redis.xpending_range(first.stream,first.group,b.entry_id,b.entry_id,1)
  assert len(pending)==1;cases+=1
  await redis.delete(broken)
  # Simulate a lost acknowledgement after the atomic publish actually committed.
  original_eval=redis.eval
  async def lost_ack(*args,**kwargs):
   await original_eval(*args,**kwargs)
   raise OSError('private-ack-marker')
  redis.eval=lost_ack
  try:await second.publish(b,output,'fixture-two')
  except OSError:pass
  finally:redis.eval=original_eval
  assert not await second.publish(b,output,'replay')
  assert await redis.xlen(output)==2
  assert (await redis.xpending(first.stream,first.group))['pending']==0
  assert await redis.xlen(first.stream)==0;cases+=1
  await redis.rpush(first.source,'retry-fixture')
  current=await first.claim()
  for attempt in range(2,5):
   await redis.xclaim(first.stream,first.group,first.consumer,0,[current.entry_id],
                     idle=SCAN_LEASE_MS+1,justid=True)
   current=await first.claim()
   assert current.attempt==attempt
  assert current.exhausted;cases+=1
  assert await first.publish(current,output,'bounded-terminal-failure');cases+=1
  await redis.rpush(invalid.source,'retained-fixture')
  await redis.set(invalid.stream,'wrong-type')
  try:await invalid.transfer_one()
  except ResponseError:pass
  else:raise AssertionError('invalid_stream_accepted')
  remaining=await redis.lrange(invalid.source,0,-1)
  assert remaining in (['retained-fixture'],[b'retained-fixture']);cases+=1
 finally:
  await redis.delete(*keys)
  remaining=await redis.exists(*keys)
  await redis.aclose()
 assert remaining==0
 return {'status':'passed','cases':cases,'fixture_cleaned':True,'serving_queue_touched':False}

try:print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':'isolated_scan_queue'}));raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_DURABLE_SCAN_QUEUE") != "1", reason="isolated dev Redis opt-in"
)
def test_scan_claim_recovery_fencing_and_atomic_publication_on_dev_redis():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=PROBE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, "isolated_scan_queue_failed"
    report = json.loads(result.stdout)
    assert report == {
        "status": "passed",
        "cases": 14,
        "fixture_cleaned": True,
        "serving_queue_touched": False,
    }
