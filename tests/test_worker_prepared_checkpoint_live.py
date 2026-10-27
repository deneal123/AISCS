"""Opt-in PostgreSQL race/rollback/process-exit proof for private checkpoints."""

import asyncio
import json
import os
import subprocess

import pytest

_PROBE = """
import asyncio,json,logging,subprocess,sys,time,uuid
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus,ServiceType
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
 CHECKPOINT_KEY,PreparedTurnCheckpoint,PreparedCheckpointInvalid,store_prepared_turn)
from service.services.chat.infrastructure.chat_worker.results.prepared import (
 PreparedResultCoordinator)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
 MutableRunState,WorkerRunRequest)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.job_state import (
 update_job_status,JobStateWriteUnavailable)
from service.services.chat.infrastructure.chat_worker.results.accepted import (
 ACCEPTED_KEY,accepted_turn,stage_accepted,promote_accepted)
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
 MATERIALIZATION_KEY,MaterializationPlan,stage_materialization)
logging.disable(logging.CRITICAL)
identity=uuid.uuid4(); thread='s37-prepared-'+identity.hex
stage='fixture'; report=None
async def main():
 global stage
 connector=PgConnector(Config().pg); owner=None; inserted=False
 try:
  owner=await ProfileRepository(connector).fetch_user_by_email(
   's37-e2e-391e5206659a3654@example.com')
  assert owner is not None
  async with connector.get_session_context() as db:
   db.add(UserLaunch(id=identity,user_id=owner.id,type=ServiceType.CHAT,
    status=ProcessingStatus.PROCESSING,payload={'thread_id':thread,'request':'synthetic'}))
   await db.commit(); inserted=True
  values={'job_id':str(identity),'owner_id':str(owner.id),'thread_id':thread,
   'reply':'synthetic accepted result','model':'synthetic/model',
   'metadata':{'execution_status':'completed'},'usage':{'total':33}}
  first=PreparedTurnCheckpoint.create(**values)
  second=PreparedTurnCheckpoint.create(**{**values,'reply':'other accepted result'})
  repository=JobRepository(connector)
  async def read():
   async with connector.get_session_context() as db:
    row=await repository.fetch_job_by_id(identity,owner.id,session=db)
    assert row is not None
    return row.payload
  stage='rollback'
  async with connector.get_session_context() as db:
   assert await store_prepared_turn(repository,db,first)
   await db.rollback()
  assert CHECKPOINT_KEY not in await read()
  async def contender(checkpoint):
   async with connector.get_session_context() as db:
    try:
     accepted=await store_prepared_turn(repository,db,checkpoint)
     await db.commit()
     return accepted
    except PreparedCheckpointInvalid:
     await db.rollback(); return False
  stage='race'
  raced=await asyncio.gather(contender(first),contender(second))
  assert sorted(raced)==[False,True]
  payload=await read(); assert payload['request']=='synthetic'
  winner=first if raced[0] else second
  assert PreparedTurnCheckpoint.decode(payload[CHECKPOINT_KEY],job_id=str(identity),
   owner_id=str(owner.id),thread_id=thread).digest==winner.digest
  stage='replay'
  async with connector.get_session_context() as db:
   assert not await store_prepared_turn(repository,db,winner)
   await db.rollback()
  stage='owner_binding'
  foreign=PreparedTurnCheckpoint.create(**{**values,'owner_id':str(uuid.uuid4())})
  async with connector.get_session_context() as db:
   try: await store_prepared_turn(repository,db,foreign)
   except PreparedCheckpointInvalid: await db.rollback()
   else: raise RuntimeError('acceptance_foreign_checkpoint_admitted')
  assert (await read())[CHECKPOINT_KEY]['sha256']==winner.digest
  stage='accepted_latch'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET payload=payload-:key '
    'WHERE id=:id AND user_id=:owner'),
    {'key':CHECKPOINT_KEY,'id':identity,'owner':owner.id})
   await db.commit()
  early=accepted_turn(job_id=str(identity),owner_id=str(owner.id),thread_id=thread,
   reply='accepted model reply',model='synthetic/model',usage={'total_tokens':33})
  stage='atomic_materialization_rollback'
  plan=MaterializationPlan.from_payload({'version':2,'reservation_id':None,
   'reserved_estimate':0,'workspace_id':None,'expires_at':None,'publications':[],
   'pricing':{'is_complex':False,'tools':[]},'elapsed_seconds':0,
   'library_files':[],'unresolved_assets':0,'context':{'metadata':{'execution_status':'completed'},
   'observations':[],'executions':[]}})
  async with connector.get_session_context() as db:
   assert await stage_materialization(repository,db,early,plan)
   inside=await repository.lock_prepared_turn(identity,owner.id,session=db)
   assert inside['payload'][ACCEPTED_KEY]==early.payload()
   assert inside['payload'][MATERIALIZATION_KEY]==plan.payload()
   assert not await stage_materialization(repository,db,early,plan)
   await db.rollback()
  rolled=await read()
  assert ACCEPTED_KEY not in rolled and MATERIALIZATION_KEY not in rolled
  stage='atomic_materialization_race'
  competing=plan.payload(); competing['reserved_estimate']=1
  other_plan=MaterializationPlan.from_payload(competing)
  async def materialization_contender(selected):
   async with connector.get_session_context() as db:
    try:
     admitted=await stage_materialization(repository,db,early,selected)
     await db.commit(); return admitted
    except PreparedCheckpointInvalid:
     await db.rollback(); return False
  raced_plans=await asyncio.gather(materialization_contender(plan),
   materialization_contender(other_plan))
  assert sorted(raced_plans)==[False,True]
  stored=await read()
  assert stored[ACCEPTED_KEY]==early.payload()
  chosen=plan if raced_plans[0] else other_plan
  assert stored[MATERIALIZATION_KEY]==chosen.payload()
  assert not await materialization_contender(chosen)
  stage='early_worker_resume'
  async with connector.get_session_context() as db:
   state=MutableRunState()
   request=WorkerRunRequest(str(identity),thread,'synthetic',str(owner.id))
   assert await PreparedResultCoordinator().restore(request=request,repository=repository,
    session=db,state=state,file_service=object())
   assert state.restored_result['reply']==early.payload()['body']['reply']
   assert state.restored_result['usage']==early.payload()['body']['usage']
   assert state.reserved_estimate==chosen.payload()['reserved_estimate']
   await db.rollback()
  promoted=await read()
  assert promoted[CHECKPOINT_KEY]['body']['usage']==early.payload()['body']['usage']
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET payload=payload-:accepted-:plan-:prepared '
    'WHERE id=:id AND user_id=:owner'),{'accepted':ACCEPTED_KEY,
    'plan':MATERIALIZATION_KEY,'prepared':CHECKPOINT_KEY,'id':identity,'owner':owner.id})
   await db.commit()
  stage='accepted_latch'
  async with connector.get_session_context() as db:
   assert await stage_accepted(repository,db,early)
   await db.rollback()
  assert ACCEPTED_KEY not in await read()
  async def early_contender(value):
   async with connector.get_session_context() as db:
    try:
     admitted=await stage_accepted(repository,db,value)
     await db.commit(); return admitted
    except PreparedCheckpointInvalid:
     await db.rollback(); return False
  rival=accepted_turn(job_id=str(identity),owner_id=str(owner.id),thread_id=thread,
   reply='other model reply',model='synthetic/model',usage={'total_tokens':34})
  results=await asyncio.gather(early_contender(early),early_contender(rival))
  assert sorted(results)==[False,True]
  early_winner=early if results[0] else rival
  assert (await read())[ACCEPTED_KEY]==early_winner.payload()
  assert not await early_contender(early_winner)
  stage='accepted_promotion'
  early_body=early_winner.payload()['body']
  promote_values={key:early_body[key] for key in
   ('job_id','owner_id','thread_id','reply','model','usage')}
  for key,value in (('reply','different reply'),('model','other/model'),
                    ('usage',{'total_tokens':999})):
   changed=PreparedTurnCheckpoint.create(**{**promote_values,key:value},metadata={})
   async with connector.get_session_context() as db:
    try: await store_prepared_turn(repository,db,changed)
    except PreparedCheckpointInvalid: await db.rollback()
    else: raise RuntimeError('direct_repository_promotion_changed_accepted_facts')
   assert CHECKPOINT_KEY not in await read()
  promoted=PreparedTurnCheckpoint.create(**promote_values,metadata={'stage':'first'})
  promoted_rival=PreparedTurnCheckpoint.create(**promote_values,metadata={'stage':'second'})
  async with connector.get_session_context() as db:
   assert await promote_accepted(repository,db,promoted)
   await db.rollback()
  assert CHECKPOINT_KEY not in await read()
  async def promoter(value):
   async with connector.get_session_context() as db:
    try:
     admitted=await promote_accepted(repository,db,value)
     await db.commit(); return admitted
    except PreparedCheckpointInvalid:
     await db.rollback(); return False
  promoted_results=await asyncio.gather(promoter(promoted),promoter(promoted_rival))
  assert sorted(promoted_results)==[False,True]
  promoted_winner=promoted if promoted_results[0] else promoted_rival
  assert (await read())[CHECKPOINT_KEY]==promoted_winner.payload()
  assert (await read())[ACCEPTED_KEY]==early_winner.payload()
  assert not await promoter(promoted_winner)
  stage='terminal_cleanup'
  before_cleanup=await read()
  for terminal_status in (ProcessingStatus.SUCCESS,ProcessingStatus.FAILURE):
   async with connector.get_session_context() as db:
    if terminal_status==ProcessingStatus.FAILURE:
     try:
      await update_job_status(repository,str(identity),terminal_status,db,str(owner.id),
       {'reply':'synthetic failure'})
     except JobStateWriteUnavailable: pass
     else: raise AssertionError('failure_erased_accepted_facts')
     await db.rollback()
     assert await read()==before_cleanup
     continue
    await update_job_status(repository,str(identity),terminal_status,db,str(owner.id),
     {'reply':'synthetic terminal',ACCEPTED_KEY:early_winner.payload(),
      CHECKPOINT_KEY:promoted_winner.payload()})
    staged=await repository.fetch_job_by_id(identity,owner.id,session=db)
    assert staged.status==terminal_status
    assert ACCEPTED_KEY not in staged.payload and CHECKPOINT_KEY not in staged.payload
    await db.rollback()
   assert await read()==before_cleanup
  async with connector.get_session_context() as db:
   await update_job_status(repository,str(identity),ProcessingStatus.SUCCESS,db,str(owner.id),
    {'reply':'synthetic terminal',ACCEPTED_KEY:early_winner.payload(),
     CHECKPOINT_KEY:promoted_winner.payload()})
   await db.commit()
  cleaned=await read()
  assert ACCEPTED_KEY not in cleaned and CHECKPOINT_KEY not in cleaned
  assert cleaned['reply']=='synthetic terminal'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET status=:status, '
    'payload=CAST(:payload AS JSONB) WHERE id=:id AND user_id=:owner'),
    {'status':'PROCESSING','payload':json.dumps(before_cleanup),'id':identity,'owner':owner.id})
   await db.commit()
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET payload=payload-:key '
    'WHERE id=:id AND user_id=:owner'),
    {'key':ACCEPTED_KEY,'id':identity,'owner':owner.id})
   await db.commit()
  stage='ambiguous_commit'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET payload=payload-:key '
    'WHERE id=:id AND user_id=:owner'),
    {'key':CHECKPOINT_KEY,'id':identity,'owner':owner.id})
   await db.commit()
  class LostCommitAcknowledgment:
   def __init__(self,session): self.session=session
   def __getattr__(self,name): return getattr(self.session,name)
   async def commit(self):
    await self.session.commit()
    raise ConnectionError('private-commit-acknowledgment-marker')
  request=WorkerRunRequest(str(identity),thread,'synthetic',str(owner.id))
  usage={'prompt_tokens':30,'completion_tokens':3,'total_tokens':33,
   'per_call_usage':[{'provider':'openai','model':'synthetic/model',
    'call_id':'synthetic-receipt','prompt':30,'completion':3}]}
  async with connector.get_session_context() as db:
   try:
    await PreparedResultCoordinator().capture(request=request,
     session=LostCommitAcknowledgment(db),repository=repository,state=MutableRunState(),
     execution_result={**usage,'metadata':{},'resolved_model':'synthetic/model'},
     reply='synthetic accepted result',metadata={},file_url=None,started_at=time.monotonic())
   except JobStateUnavailable as error:
    assert str(error)=='Prepared result unavailable'
   else: raise RuntimeError('ambiguous_commit_not_bounded')
  accepted=await read()
  assert accepted['request']=='synthetic'
  assert accepted[CHECKPOINT_KEY]['body']['usage']==usage
  assert accepted[CHECKPOINT_KEY]['body']['reply']=='synthetic accepted result'
  stage='ambiguous_restore'
  for _ in range(2):
   state=MutableRunState()
   async with connector.get_session_context() as db:
    assert await PreparedResultCoordinator().restore(request=request,repository=repository,
     session=db,state=state,file_service=object())
    assert state.restored_result['usage']==usage
    assert state.restored_result['reply']=='synthetic accepted result'
    assert state.settled_credits==0
    await db.rollback()
  assert (await read())[CHECKPOINT_KEY]==accepted[CHECKPOINT_KEY]
  stage='process_exit'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET payload=payload-:key '
    'WHERE id=:id AND user_id=:owner'),
    {'key':CHECKPOINT_KEY,'id':identity,'owner':owner.id})
   await db.commit()
  child='''import asyncio,json,logging,os
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
 PreparedTurnCheckpoint,store_prepared_turn)
logging.disable(logging.CRITICAL)
async def produce():
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  checkpoint=PreparedTurnCheckpoint.create(**json.loads(VALUES))
  assert await store_prepared_turn(JobRepository(connector),db,checkpoint)
  await db.commit()
 os._exit(73)
asyncio.run(produce())
'''.replace('VALUES',repr(json.dumps(values)))
  produced=await asyncio.to_thread(subprocess.run,[sys.executable,'-'],
   input=child.encode(),capture_output=True,timeout=30,check=False)
  assert produced.returncode==73
  restored=await read()
  assert restored['request']=='synthetic'
  assert PreparedTurnCheckpoint.decode(restored[CHECKPOINT_KEY],job_id=str(identity),
   owner_id=str(owner.id),thread_id=thread).digest==first.digest
  stage='terminal'
  async with connector.get_session_context() as db:
   await db.execute(text('UPDATE profile.user_launch SET status=:status '
    'WHERE id=:id AND user_id=:owner'),
    {'id':identity,'owner':owner.id,'status':'SUCCESS'})
   await db.commit()
  assert not await contender(first)
  return {'atomic_winner':True,'rollback':True,'replay_noop':True,
   'owner_bound':True,'process_exit_recovered':True,'terminal_preserved':True,
   'ambiguous_commit_recovered':True,'restore_replay_read_only':True,
   'accepted_latch_atomic':True,'accepted_latch_rollback':True,
   'promotion_preserves_accepted':True,'promotion_atomic':True,'promotion_rollback':True,
   'terminal_cleanup_committed':True,'terminal_cleanup_rollback_preserves_latches':True}
 finally:
  if inserted:
   stage='cleanup'
   async with connector.get_session_context() as db:
    await db.execute(text('DELETE FROM profile.user_launch WHERE id=:id '
     "AND user_id=:owner AND payload->>'thread_id'=:thread"),
     {'id':identity,'owner':owner.id,'thread':thread})
    await db.commit()
    assert await db.scalar(text('SELECT count(*) FROM profile.user_launch WHERE id=:id'),
     {'id':identity})==0
try: report=asyncio.run(main())
except Exception: report={'status':'failed','stage':stage}
print(json.dumps(report))
if report.get('status')=='failed': raise SystemExit(1)
"""


def test_prepared_checkpoint_probe_compiles_without_execution():
    compile(_PROBE, "<prepared-checkpoint-acceptance>", "exec")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_PREPARED_CHECKPOINT") != "1", reason="isolated dev PostgreSQL fixture"
)
async def test_prepared_checkpoint_is_atomic_and_survives_committed_process_exit():
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=_PROBE.encode(),
        capture_output=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        stage = "unknown"
        try:
            response = json.loads(result.stdout)
            if response.get("stage") in {
                "fixture",
                "rollback",
                "race",
                "replay",
                "owner_binding",
                "accepted_latch",
                "accepted_promotion",
                "terminal_cleanup",
                "ambiguous_commit",
                "ambiguous_restore",
                "process_exit",
                "terminal",
                "cleanup",
            }:
                stage = response["stage"]
        except (ValueError, AttributeError):
            pass
        pytest.fail("prepared_checkpoint_acceptance_failed:" + stage)
    assert json.loads(result.stdout) == {
        "atomic_winner": True,
        "rollback": True,
        "replay_noop": True,
        "owner_bound": True,
        "process_exit_recovered": True,
        "terminal_preserved": True,
        "ambiguous_commit_recovered": True,
        "restore_replay_read_only": True,
        "accepted_latch_atomic": True,
        "accepted_latch_rollback": True,
        "promotion_preserves_accepted": True,
        "promotion_atomic": True,
        "promotion_rollback": True,
        "terminal_cleanup_committed": True,
        "terminal_cleanup_rollback_preserves_latches": True,
    }
