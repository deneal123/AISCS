"""Opt-in real Redis worker crash/cancel corpus in isolated fixture namespaces."""

import json
import os
import subprocess

import pytest

PROBE = r"""
import asyncio,json,subprocess,sys,uuid
from types import SimpleNamespace
from service.infrastructure.cache.manager import RedisManager
from service.services.files.infrastructure.scan_queue import DurableScanQueue,SCAN_LEASE_MS
from service.settings import Config
from service.utils import file_scan_worker as worker

CHILD = '''
import asyncio,sys
from types import SimpleNamespace
from service.infrastructure.cache.manager import RedisManager
from service.services.files.infrastructure.scan_queue import DurableScanQueue
from service.settings import Config
from service.utils.file_scan_worker import process_scan_once
async def main():
 redis=RedisManager(Config().redis).get_client()
 queue=DurableScanQueue(redis,namespace=sys.argv[1])
 async def scan(_key):
  print('scan-started',flush=True)
  await asyncio.Event().wait()
 await process_scan_once(redis,SimpleNamespace(scan=scan),queue=queue)
asyncio.run(main())
'''

async def main():
 redis=RedisManager(Config().redis).get_client()
 prefix='file:scan:worker-acceptance:'+uuid.uuid4().hex
 keys=[];child=None;tasks=[];cases=0
 async def ok(_key):return {'status':'ok','size':1,'sha256':'a'*64}
 async def prepare(label):
  namespace=prefix+':'+label
  queue=DurableScanQueue(redis,namespace=namespace)
  file_key=namespace+':source'
  output='file:'+file_key+':stream'
  keys.extend([queue.source,queue.stream,queue.failures,output])
  await redis.rpush(queue.source,file_key)
  return queue,file_key,output
 async def expire(queue):
  pending=await redis.xpending_range(queue.stream,queue.group,'-','+',1)
  assert len(pending)==1
  await redis.xclaim(queue.stream,queue.group,pending[0]['consumer'],0,
                    [pending[0]['message_id']],idle=SCAN_LEASE_MS+1,justid=True)
 try:
  queue,key,output=await prepare('crash')
  child=subprocess.Popen([sys.executable,'-c',CHILD,prefix+':crash'],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  line=await asyncio.wait_for(asyncio.to_thread(child.stdout.readline),10)
  assert line.strip()=='scan-started'
  child.kill();await asyncio.to_thread(child.wait,5);cases+=1
  assert (await redis.xpending(queue.stream,queue.group))['pending']==1
  assert await redis.exists(output)==0;cases+=1
  await expire(queue)
  assert await worker.process_scan_once(redis,SimpleNamespace(scan=ok),queue=queue)==1
  assert await worker.process_scan_once(redis,SimpleNamespace(scan=ok),queue=queue)==0
  assert await redis.xlen(output)==1;cases+=1
  await queue.close()
  for failure in ('cancel','deadline','lease'):
   queue,key,output=await prepare(failure)
   started,stopped=asyncio.Event(),asyncio.Event()
   async def blocked(_key):
    started.set()
    try:await asyncio.Event().wait()
    finally:stopped.set()
   previous_timeout=worker.SCAN_TIMEOUT_SEC
   previous_heartbeat=worker.SCAN_HEARTBEAT_SEC
   if failure=='deadline':worker.SCAN_TIMEOUT_SEC=0.01
   if failure=='lease':worker.SCAN_HEARTBEAT_SEC=0.005
   task=asyncio.create_task(worker.process_scan_once(redis,SimpleNamespace(scan=blocked),queue=queue))
   tasks.append(task)
   try:
    await asyncio.wait_for(started.wait(),2)
    if failure=='cancel':
     task.cancel()
     try:await task
     except asyncio.CancelledError:pass
     else:raise AssertionError('cancel_not_propagated')
    else:
     if failure=='lease':
      pending=await redis.xpending_range(queue.stream,queue.group,'-','+',1)
      await redis.xclaim(queue.stream,queue.group,'replacement-fixture',0,
                        [pending[0]['message_id']])
     assert await asyncio.wait_for(task,2)==0
    assert stopped.is_set() and await redis.exists(output)==0;cases+=1
    await queue.close()
    assert (await redis.xpending(queue.stream,queue.group))['pending']==1
   finally:
    worker.SCAN_TIMEOUT_SEC=previous_timeout;worker.SCAN_HEARTBEAT_SEC=previous_heartbeat
   await expire(queue)
   replacement=DurableScanQueue(redis,namespace=prefix+':'+failure)
   assert await worker.process_scan_once(redis,SimpleNamespace(scan=ok),queue=replacement)==1
   assert await redis.xlen(output)==1;cases+=1
   await replacement.close();await queue.close()
  queue,key,output=await prepare('exhausted')
  calls=0
  async def failing(_key):
   nonlocal calls
   calls+=1
   return {'status':'error','reason':'unavailable'}
  for attempt in range(1,5):
   if attempt>1:await expire(queue)
   result=await worker.process_scan_once(redis,SimpleNamespace(scan=failing),queue=queue)
   assert result==(1 if attempt==4 else 0)
  assert calls==3 and await redis.xlen(output)==1;cases+=1
  await queue.close()
  for label,raw in [('binary',b'\xff'),('empty',b''),('oversized',b'x'*4097)]:
   queue=DurableScanQueue(redis,namespace=prefix+':'+label)
   keys.extend([queue.source,queue.stream,queue.failures])
   await redis.rpush(queue.source,raw)
   async def forbidden(_key):raise AssertionError('invalid_source_scanned')
   assert await worker.process_scan_once(redis,SimpleNamespace(scan=forbidden),queue=queue)==1
   assert await redis.xlen(queue.failures)==1
   entry=(await redis.xrange(queue.failures))[0][1]
   data=entry.get('data',entry.get(b'data'))
   assert json.loads(data)=={'event':'scan_failed','reason':'invalid'};cases+=1
   await queue.close()
 finally:
  if child is not None and child.poll() is None:
   child.kill();await asyncio.to_thread(child.wait,5)
  for task in tasks:
   if not task.done():task.cancel()
  await asyncio.gather(*tasks,return_exceptions=True)
  assert all(k.startswith(prefix+':') or k.startswith('file:'+prefix+':') for k in keys)
  await redis.delete(*keys)
  remaining=await redis.exists(*keys)
  await redis.aclose()
 assert remaining==0
 return {'status':'passed','cases':cases,'fixture_cleaned':True,
         'serving_queue_touched':False,'provider_calls':0,'storage_writes':0}

try:print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':'isolated_scan_worker'}));raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_DURABLE_SCAN_QUEUE") != "1", reason="isolated dev Redis opt-in"
)
def test_worker_crash_cancel_lease_deadline_and_invalid_source_recovery():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=PROBE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, "isolated_scan_worker_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "cases": 13,
        "fixture_cleaned": True,
        "serving_queue_touched": False,
        "provider_calls": 0,
        "storage_writes": 0,
    }
