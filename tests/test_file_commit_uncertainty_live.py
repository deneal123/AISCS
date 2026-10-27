"""Opt-in real PostgreSQL commit recovery; object storage is deliberately simulated."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config,JobConfig,config
from service.infrastructure.database.postgresql import PgConnector
from service.models.key_value import ServiceType
from service.services.files.persistence.file_repository import FileRepository
from service.services.files.application.file_saver_service import FileSaverService
from service.infrastructure.agents_client import agent_file_bridge as bridge
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.jobs.application.job_service import JobService
from fastapi import HTTPException
stage='fixture'
async def main():
 global stage
 import inspect
 from pathlib import Path
 from service.services.jobs.application.job_application_service import JobApplicationService
 stage='source_freshness'
 assert hashlib.sha256(Path(inspect.getfile(JobApplicationService)).read_bytes()).hexdigest()==(
  '__APPLICATION_DIGEST__')
 assert hashlib.sha256(Path(inspect.getfile(JobRepository)).read_bytes()).hexdigest()==(
  '__REPOSITORY_DIGEST__')
 from service.services.chat.infrastructure.chat_worker.execution.cancellation import run_with_cancel
 assert hashlib.sha256(Path(inspect.getfile(run_with_cancel)).read_bytes()).hexdigest()==(
  '__CANCELLATION_DIGEST__')
 stage='fixture'
 connector=PgConnector(Config().pg); owner=None; saved=[]; identity=uuid.uuid4().hex
 rejected=0; original_admins=config.service.admin_user_ids; extra_jobs=[]
 repository=FileRepository(connector)
 job_thread='s37-owner-job-'+identity
 try:
  async with connector.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   initial=await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
    {'owner':owner})
  class LostAcknowledgement:
   def __getattr__(self,name): return getattr(repository,name)
   async def add_file_metadata(self,row):
    result=await repository.add_file_metadata(row)
    saved.append(result.id)
    raise RuntimeError('private-commit-ack-marker')
  class Storage:
   objects={}; deleted=[]
   def build_file_path(self,*parts): return 's37-commit/'+identity+'/'+parts[-1]
   async def upload_file(self,*,file_key,file_data):
    self.objects[file_key]=file_data; return 'internal://synthetic-object'
   async def upload_file_stream(self,*,file_key,stream,length):
    data=stream.read(); assert len(data)==length
    return await self.upload_file(file_key=file_key,file_data=data)
   async def delete_file(self,*,file_key):
    self.deleted.append(file_key); self.objects.pop(file_key,None)
  storage=Storage(); service=FileSaverService(LostAcknowledgement(),'uploads',storage)
  body=b'synthetic commit boundary'
  async def chunks(): yield body
  for streaming,with_intent in ((False,False),(False,True),(True,True)):
   stage='stream_commit' if streaming else 'buffered_commit'
   intent=uuid.uuid4() if with_intent else None
   if streaming:
    response=await service.save_stream(owner,ServiceType.CHAT,'commit.pdf',chunks(),
     expected_size=len(body),expected_sha256=hashlib.sha256(body).hexdigest(),
     upload_intent_id=intent)
   else:
    response=await service.save(owner,ServiceType.CHAT,'commit.pdf',body,upload_intent_id=intent)
   assert response.reused and response.file_id==saved[-1] and not storage.deleted
   fresh=await repository.fetch_user_file_by_id(owner,response.file_id)
   assert fresh is not None and fresh.content_sha256==hashlib.sha256(body).hexdigest()
   assert storage.objects[fresh.file_name]==body
   if intent is not None:
    if streaming:
     replay=await service.save_stream(owner,ServiceType.CHAT,'commit.pdf',chunks(),
      expected_size=len(body),expected_sha256=hashlib.sha256(body).hexdigest(),
      upload_intent_id=intent)
    else:
     replay=await service.save(owner,ServiceType.CHAT,'commit.pdf',body,upload_intent_id=intent)
    assert replay.reused and replay.file_id==response.file_id
  assert len(saved)==3 and len(storage.objects)==3
  stage='foreign_owner_integrity'
  config.service.admin_user_ids=[str(owner)]
  # These UUIDs have no user row. The DB must reject them; the configured admin
  # must not silently become their artifact owner.
  import base64
  for key in ('file_b64','pptx_b64','b64_json'):
   foreign=uuid.uuid4()
   async with connector.get_session_context() as db:
    assert await db.scalar(text('SELECT count(*) FROM profile."user" WHERE id=:id'),
     {'id':foreign})==0
   artifact={key:base64.b64encode(b'synthetic owner boundary').decode()}
   if key=='file_b64': artifact['filename']='owner-notes.md'
   url,meta=await bridge.persist_generated_artifacts(
    file_service=FileSaverService(repository,'uploads',storage),user_id=str(foreign),
    metadata={'_pending_artifacts':[artifact]},job_id='s37-owner-'+identity)
   assert url is None and not meta.get('generated_files')
   async with connector.get_session_context() as db:
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file '
     'WHERE user_id=:owner'),{'owner':owner})==initial+3
   assert len(storage.objects)==3
   rejected+=1
  assert rejected==3
  stage='invalid_owner_admission'
  for invalid in (None,'anonymous','null',uuid.UUID(int=0)):
   url,meta=await bridge.persist_generated_artifacts(
    file_service=FileSaverService(repository,'uploads',storage),user_id=invalid,
    metadata={'_pending_artifacts':[{'file_b64':base64.b64encode(body).decode(),
     'filename':'invalid-owner.md','required':True}]},job_id='s37-owner-'+identity)
   assert url is None and not meta.get('generated_files') and '_pending_artifacts' not in meta
   assert len(storage.objects)==3
  async with connector.get_session_context() as db:
   assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
    {'owner':owner})==initial+3
  stage='job_owner_admission'
  jobs=JobService(JobConfig(),JobRepository(connector))
  for invalid in (None,uuid.UUID(int=0),uuid.uuid4()):
   try:
    await jobs.create_chat_job(invalid,job_thread,'synthetic owner admission')
   except HTTPException as exc:
    assert exc.status_code in (400,500)
   else: raise AssertionError('foreign_job_created')
  job=await jobs.create_chat_job(owner,job_thread,'synthetic owner admission')
  async with connector.get_session_context() as db:
   rows=(await db.execute(text('SELECT id,user_id FROM profile.user_launch '
    "WHERE payload->>'thread_id'=:thread"),{'thread':job_thread})).all()
   assert rows==[(job.job_id,owner)]
  stage='chat_polling_authority'
  from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn
  import json
  accepted=accepted_turn(job_id=str(job.job_id),owner_id=str(owner),thread_id=job_thread,
   reply='synthetic polling receipt',model='synthetic',usage={'total_tokens':3}).payload()
  async with connector.get_session_context() as db:
   await db.execute(text("UPDATE profile.user_launch SET status='PROCESSING',"
    "celery_task_id='synthetic-task',payload=payload::jsonb || CAST(:facts AS jsonb) "
    'WHERE id=:id AND user_id=:owner'),{'id':job.job_id,'owner':owner,
    'facts':json.dumps({'_accepted_turn_v1':accepted})})
   await db.commit()
  class PollingQueue:
   def get_task_state(self,task_id):
    raise AssertionError('chat_polling_consulted_transport')
  jobs.job_queue=PollingQueue()
  response=await jobs.fetch_job_result(owner,job.job_id)
  assert response.status.value=='PROCESSING' and response.celery_task_id=='synthetic-task'
  stage='task_owner_control'
  from service.services.jobs.application.job_application_service import JobApplicationService
  control=JobApplicationService(jobs)
  task_status=await control.get_task_status('synthetic-task',user_id=owner)
  assert task_status.state=='STARTED' and task_status.result is None
  assert await control.cancel_task('synthetic-task',user_id=owner)=={
   'task_id':'synthetic-task','cancelled':False}
  for method in (control.get_task_status,control.cancel_task):
   try: await method('synthetic-task',user_id=uuid.uuid4())
   except HTTPException as exc: assert exc.status_code==404
   else: raise AssertionError('foreign_task_access')
  stage='cancel_acceptance_race'
  from service.infrastructure.cache.manager import RedisManager
  manager=RedisManager(Config().redis); actual_redis=manager.get_client()
  race_task='s37-cancel-'+identity
  race_key='chat:cancel:'+race_task
  try:
   async with connector.get_session_context() as db:
    await db.execute(text('UPDATE profile.user_launch SET celery_task_id=:task,'
     "payload=payload::jsonb - '_accepted_turn_v1' WHERE id=:id AND user_id=:owner"),
     {'task':race_task,'id':job.job_id,'owner':owner})
    await db.commit()
   class RaceRedis:
    async def set(self,key,value,ex):
     ack=await actual_redis.set(key,value,ex=ex)
     # Accept and commit after owner lookup, before cancellation returns.
     async with connector.get_session_context() as db:
      await db.execute(text('UPDATE profile.user_launch SET '
       'payload=payload::jsonb || CAST(:facts AS jsonb) WHERE id=:id AND user_id=:owner'),
       {'id':job.job_id,'owner':owner,'facts':json.dumps({'_accepted_turn_v1':accepted})})
      await db.commit()
     return ack
   race_control=JobApplicationService(jobs,RaceRedis())
   assert await race_control.cancel_task(race_task,user_id=owner)=={
    'task_id':race_task,'cancelled':False}
   assert await actual_redis.get(race_key) in ('1',b'1')
   assert 0<await actual_redis.ttl(race_key)<=120
  finally:
   await actual_redis.delete(race_key)
   assert not await actual_redis.exists(race_key)
   assert not await jobs.repository.is_chat_cancel_requested(job.job_id,owner,job_thread)
   await manager.close()
  async with connector.get_session_context() as db:
   fresh=(await db.execute(text('SELECT status,payload FROM profile.user_launch '
    'WHERE id=:id AND user_id=:owner'),{'id':job.job_id,'owner':owner})).mappings().one()
   assert fresh['status']=='PROCESSING' and fresh['payload']['_accepted_turn_v1']==accepted
  stage='durable_queued_cancel'
  job_repo=JobRepository(connector)
  from service.services.chat.infrastructure.chat_worker.execution.job_state import (
   redelivery_short_circuit,
  )
  from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
   CancelledByUser,
  )
  async with connector.get_session_context() as db:
   await db.execute(text("UPDATE profile.user_launch SET status='NEW',"
    "payload=payload::jsonb - '_accepted_turn_v1' WHERE id=:id AND user_id=:owner"),
    {'id':job.job_id,'owner':owner})
   await db.commit()
  manager=RedisManager(Config().redis); actual_redis=manager.get_client()
  try:
   queued_control=JobApplicationService(jobs,actual_redis)
   stale=await job_repo.fetch_job_by_id(job.job_id,owner)
   for repeat in range(2):
    assert await queued_control.cancel_task(race_task,user_id=owner)=={
     'task_id':race_task,'cancelled':True}
   # Delete the exact flag to model expiry: SQL intent must remain authoritative.
   await actual_redis.delete(race_key)
   assert not await actual_redis.exists(race_key)
   stage='durable_executing_cancel'
   assert await job_repo.is_chat_cancel_requested(job.job_id,owner,job_thread)
   assert not await job_repo.is_chat_cancel_requested(job.job_id,uuid.uuid4(),job_thread)
   assert not await job_repo.is_chat_cancel_requested(job.job_id,owner,'foreign-thread')
   from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
    run_with_cancel,
   )
   execution_cleaned=asyncio.Event()
   async def execution():
    try: await asyncio.Event().wait()
    finally: execution_cleaned.set()
   async def durable_cancel():
    return await job_repo.is_chat_cancel_requested(job.job_id,owner,job_thread)
   try:
    await asyncio.wait_for(run_with_cancel(execution(),redis_client=None,
     celery_task_id=race_task,poll_interval=0.01,durable_cancel=durable_cancel),timeout=5)
   except CancelledByUser: pass
   else: raise AssertionError('executing_cancel_not_observed')
   assert execution_cleaned.is_set()
   stage='bounded_sql_cancel_observation'
   sql_closed=asyncio.Event()
   async def stalled_cancel():
    try:
     async with connector.get_session_context() as observation:
      await observation.execute(text('SELECT pg_sleep(5)'))
    finally: sql_closed.set()
    return False
   async def normal_completion():
    await sql_closed.wait()
    return {'reply':'synthetic completed'}
   bounded=await asyncio.wait_for(run_with_cancel(normal_completion(),redis_client=None,
    celery_task_id=race_task,poll_interval=0.01,durable_cancel=stalled_cancel),timeout=5)
   assert bounded=={'reply':'synthetic completed'}
   async with connector.get_session_context() as observation:
    assert await observation.scalar(text('SELECT 1'))==1
   stage='cancel_marker_stale_update'
   from service.models.key_value import ProcessingStatus
   stale.status=ProcessingStatus.PROCESSING
   await job_repo.update_job_status(stale)
   preserved=await job_repo.fetch_job_by_id(job.job_id,owner)
   assert preserved.payload.get('_cancel_requested_v1') is True
   from service.shared.repositories.exceptions import RepositoryNotFoundError
   foreign_write=stale.model_copy(update={'user_id':uuid.uuid4()})
   try: await job_repo.update_job_status(foreign_write)
   except RepositoryNotFoundError: pass
   else: raise AssertionError('foreign_status_write')
   assert not await job_repo.request_chat_cancel(job.job_id,uuid.uuid4())
   async with connector.get_session_context() as db:
    try:
     await redelivery_short_circuit(job_repo,str(job.job_id),db,str(owner))
    except CancelledByUser: pass
    else: raise AssertionError('queued_cancel_started_new_work')
    fresh=(await db.execute(text('SELECT status,payload FROM profile.user_launch '
     'WHERE id=:id AND user_id=:owner'),{'id':job.job_id,'owner':owner})).mappings().one()
    assert fresh['status']=='PROCESSING' and fresh['payload']['_cancel_requested_v1'] is True
    assert fresh['payload']['thread_id']==job_thread
  finally:
   await actual_redis.delete(race_key)
   await manager.close()
   assert 'meta' not in fresh['payload']
  async with connector.get_session_context() as db:
   await db.execute(text("UPDATE profile.user_launch SET status='PROCESSING',"
    'payload=payload::jsonb || CAST(:facts AS jsonb) WHERE id=:id AND user_id=:owner'),
    {'id':job.job_id,'owner':owner,'facts':json.dumps({'_accepted_turn_v1':accepted})})
   await db.commit()
   assert await redelivery_short_circuit(job_repo,str(job.job_id),db,str(owner)) is None
  assert not await job_repo.is_chat_cancel_requested(job.job_id,owner,job_thread)
  stage='recovery_checkpoint_stale_update'
  await job_repo.update_job_status(stale)
  retained=await job_repo.fetch_job_by_id(job.job_id,owner)
  assert retained.payload['_accepted_turn_v1']==accepted
  stage='chat_stale_cleanup_authority'
  async with connector.get_session_context() as db:
   await db.execute(text("UPDATE profile.user_launch SET updated_at=clock_timestamp() "
    "-interval '365 days' WHERE id=:id AND user_id=:owner"),{'id':job.job_id,'owner':owner})
   await db.commit()
  job_repo=JobRepository(connector)
  class ScopedJobs:
   # Restrict scans to this exact fixture: no unrelated dev-user job can be cleaned.
   def __getattr__(self,name): return getattr(job_repo,name)
   async def fetch_jobs_by_user_id(self,user_id,statuses):
    assert user_id==owner
    row=await job_repo.fetch_job_by_id(job.job_id,owner)
    return [row] if row is not None and row.status in statuses else []
   async def create_job(self,value):
    created=await job_repo.create_job(value); extra_jobs.append(created.id); return created
  from service.services.jobs.application.dto import StartJobRequest
  try:
   await JobService(JobConfig(),ScopedJobs()).create_job(owner,
    StartJobRequest(file_id=uuid.uuid4(),type=ServiceType.CHAT))
  except HTTPException as exc: assert exc.status_code==400
  else: raise AssertionError('stale_chat_finalized')
  assert not extra_jobs
  async with connector.get_session_context() as db:
   fresh=(await db.execute(text('SELECT status,payload FROM profile.user_launch '
    'WHERE id=:id AND user_id=:owner'),{'id':job.job_id,'owner':owner})).mappings().one()
   assert fresh['status']=='PROCESSING' and fresh['payload']['_accepted_turn_v1']==accepted
  stage='terminal_stale_update'
  from service.shared.repositories.exceptions import RepositoryError
  async with connector.get_session_context() as db:
   await db.execute(text("UPDATE profile.user_launch SET status='SUCCESS',"
    'payload=CAST(:facts AS jsonb) WHERE id=:id AND user_id=:owner'),
    {'id':job.job_id,'owner':owner,'facts':json.dumps({'reply':'synthetic terminal'})})
   await db.commit()
  try: await job_repo.update_job_status(stale)
  except RepositoryError: pass
  else: raise AssertionError('terminal_job_reopened')
  terminal=await job_repo.fetch_job_by_id(job.job_id,owner)
  assert terminal.status==ProcessingStatus.SUCCESS
  assert terminal.payload=={'reply':'synthetic terminal'}
 finally:
  config.service.admin_user_ids=original_admins
  previous_stage=stage
  stage='cleanup'
  if owner is not None:
   async with connector.get_session_context() as db:
    for extra_id in extra_jobs:
     await db.execute(text('DELETE FROM profile.user_launch WHERE id=:id AND user_id=:owner'),
      {'id':extra_id,'owner':owner})
    await db.execute(text('DELETE FROM profile.user_launch WHERE user_id=:owner '
     "AND payload->>'thread_id'=:thread"),{'owner':owner,'thread':job_thread})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.user_launch '
     "WHERE payload->>'thread_id'=:thread"),{'thread':job_thread})==0
   # Include any wrongly-owned row from a regressed implementation so a failed
   # acceptance also cleans only this exact fixture's namespace.
   async with connector.get_session_context() as db:
    fixture_ids=(await db.execute(text('SELECT id FROM profile.user_file '
     'WHERE user_id=:owner AND file_name LIKE :prefix'),
     {'owner':owner,'prefix':'s37-commit/'+identity+'/%'})).scalars().all()
   for file_id in fixture_ids:
    await repository.delete_file_metadata(user_id=owner,file_id=file_id)
   async with connector.get_session_context() as db:
    assert await db.scalar(text('SELECT count(*) FROM profile.user_file WHERE user_id=:owner'),
     {'owner':owner})==initial
  await connector.close()
  stage=previous_stage
try:
 asyncio.run(main()); print(json.dumps({'status':'passed','committed_uploads':3,
  'owner_integrity_rejections':3,'invalid_owner_rejections':4,'job_owner_rejections':3,
  'chat_polling_sql_authority':True,'chat_stale_cleanup_preserved':True,
  'task_owner_control':True,'cancel_acceptance_race':True,'durable_queued_cancel':True,
  'cancel_marker_stale_update':True,'recovery_transition_fencing':True,
  'durable_executing_cancel':True,'bounded_sql_observation':True}))
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_commit_probe_is_valid_python_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_FILE_COMMIT") != "1", reason="explicit dev PostgreSQL acceptance"
)
def test_committed_uploads_survive_lost_acknowledgement_and_reuse_their_rows():
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
        input=_PROBE.replace(
            "__APPLICATION_DIGEST__",
            hashlib.sha256(
                Path("service/services/jobs/application/job_application_service.py").read_bytes()
            ).hexdigest(),
        )
        .replace(
            "__REPOSITORY_DIGEST__",
            hashlib.sha256(
                Path("service/services/jobs/persistence/job_repository.py").read_bytes()
            ).hexdigest(),
        )
        .replace(
            "__CANCELLATION_DIGEST__",
            hashlib.sha256(
                Path(
                    "service/services/chat/infrastructure/chat_worker/execution/cancellation.py"
                ).read_bytes()
            ).hexdigest(),
        )
        .encode(),
        capture_output=True,
        cwd="..",
        timeout=90,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "file_commit_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "file_commit_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["committed_uploads"] == 3
    assert report["owner_integrity_rejections"] == 3
    assert report["invalid_owner_rejections"] == 4
    assert report["job_owner_rejections"] == 3
    assert report["chat_polling_sql_authority"]
    assert report["chat_stale_cleanup_preserved"]
    assert report["task_owner_control"]
    assert report["cancel_acceptance_race"]
    assert report["durable_queued_cancel"]
    assert report["cancel_marker_stale_update"]
    assert report["recovery_transition_fencing"]
    assert report["durable_executing_cancel"]
    assert report["bounded_sql_observation"]
