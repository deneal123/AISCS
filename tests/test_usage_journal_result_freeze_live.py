"""Rollback-only actual PostgreSQL predicate probe; no provider or charge."""

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
from sqlalchemy import select,text
from service.settings import config
from service.infrastructure.database.postgresql import PgConnector
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus,ServiceType
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
 stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
stage='freshness'
async def main():
 global stage
 assert hashlib.sha256(Path(inspect.getfile(JobRepository)).read_bytes()).hexdigest()=='__DIGEST__'
 connector=PgConnector(config.pg); repo=JobRepository(connector); jobs=[]
 try:
  for key in ('_accepted_turn_v1','_prepared_turn_v1','_materialization_plan_v1'):
   stage=key
   async with connector.get_session_context() as db:
    try:
     owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
       {'email':'s38-video-acceptance@example.com'})
     assert owner is not None
     job=uuid.uuid4(); jobs.append(job); attempt=str(uuid.uuid4()); thread=str(uuid.uuid4())
     previous={'schema_version':1,'attempt_id':attempt,'revision':1,'receipts':[{
       'receipt_id':'fixture','provider':'gigachat','model':'GigaChat-2','kind':None,
       'prompt':20,'completion':2,'estimated':True}]}
     payload={'thread_id':thread,'_execution_attempt_v1':attempt,key:{},'_usage_journal_v1':previous}
     db.add(UserLaunch(id=job,user_id=owner,type=ServiceType.CHAT,
       status=ProcessingStatus.PROCESSING,payload=payload))
     await db.flush()
     assert not await stage_usage_journal(repo,db,job_id=job,owner_id=owner,
       thread_id=thread,payload=previous)
     incoming={**previous,'revision':2,'receipts':[{**previous['receipts'][0],
       'prompt':19,'completion':3,'estimated':False}]}
     assert not await repo.stage_usage_journal(
       job,owner,thread,attempt,json.dumps(incoming),session=db)
     try:
      await stage_usage_journal(repo,db,job_id=job,owner_id=owner,
        thread_id=thread,payload=incoming)
     except JobStateUnavailable:
      pass
     else:
      raise AssertionError('changed_journal_was_admitted')
     saved=await db.scalar(select(UserLaunch.payload).where(UserLaunch.id==job))
     assert saved['_usage_journal_v1']==previous
    finally:
     await db.rollback()
  stage='cleanup'
  async with connector.get_session_context() as db:
   assert not list((await db.scalars(select(UserLaunch.id).where(UserLaunch.id.in_(jobs)))).all())
   await db.rollback()
  print(json.dumps({'status':'passed','predicates':3,'persisted_jobs':0}))
 finally:
  await connector.close()
try:
 asyncio.run(main())
except Exception:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_rollback_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_USAGE_FREEZE") != "1", reason="opt-in rollback-only dev SQL"
)
def test_actual_repository_freezes_usage_after_result_latches():
    source = Path("service/services/jobs/persistence/job_repository.py")
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=_PROBE.replace(
            "__DIGEST__", hashlib.sha256(source.read_bytes()).hexdigest()
        ).encode(),
        capture_output=True,
        timeout=60,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert lines, "usage_freeze_probe_missing_result"
    report = json.loads(lines[-1])
    assert result.returncode == 0 and report.get("status") == "passed", (
        "usage_freeze_probe_failed_" + str(report.get("stage", "unknown"))
    )
    assert report["predicates"] == 3 and report["persisted_jobs"] == 0
