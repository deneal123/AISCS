"""Opt-in question admission proof in a disposable DB; no dev migration or queue."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

FILES = (
    "alembic/versions/041_human_questions.py",
    "service/services/chat/domain/human_questions/contracts.py",
    "service/services/chat/domain/human_questions/resume.py",
    "service/services/chat/persistence/human_questions/repository.py",
    "service/services/chat/persistence/human_questions/dispatch.py",
    "service/services/chat/domain/human_questions/dispatch.py",
    "service/services/chat/application/human_questions/dispatch.py",
    "service/services/chat/domain/human_questions/cost.py",
    "service/services/chat/persistence/human_questions/cost.py",
    "service/services/jobs/persistence/job_repository.py",
    "service/services/jobs/persistence/question_cancellation.py",
)
PROBE = r"""
import asyncio,hashlib,importlib.util,json,logging,re,sys,time,uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import asyncpg
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession,async_sessionmaker,create_async_engine
from service.settings import config
from service.services.chat.domain.human_questions.contracts import (
 QuestionRefusal,QuestionPause,QuestionPrompt,QuestionScope,freeze_continuation,
 freeze_question_continuation)
from service.services.chat.domain.human_questions.resume import QuestionResume,RESUME_CONTEXT_KEY
from service.services.chat.domain.human_questions.cost import QuestionCost,COST_KEY
from service.services.chat.persistence.human_questions.cost import HumanQuestionCostRepository
from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.persistence.human_questions.dispatch import (
 HumanQuestionDispatchRepository)
from service.services.chat.application.human_questions.dispatch import dispatch_question_children
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.chat.persistence.human_questions.repository import HumanQuestionRepository
from service.shared.repositories.exceptions import RepositoryError
logging.disable(logging.CRITICAL)
stage='source_parity'
class AckSession(AsyncSession):
 async def commit(self):
  lose=self.info.pop('lose_ack',False)
  await super().commit()
  if lose: raise OperationalError('PRIVATE',{},Exception('PRIVATE'))
async def main():
 global stage
 files=json.load(sys.stdin)['files']
 assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
  for path,digest in files.items())
 assert config.pg.host=='postgres'
 database='gpthub_question_'+uuid.uuid4().hex[:24]
 assert re.fullmatch(r'gpthub_question_[0-9a-f]{24}',database)
 admin=await asyncpg.connect(host=config.pg.host,port=config.pg.port,user=config.pg.user,
  password=config.pg.password,database=config.pg.db,timeout=5)
 engine=None; created=False; count=0
 try:
  stage='fixture_database'
  await admin.execute('CREATE DATABASE "'+database+'"'); created=True
  engine=create_async_engine(URL.create('postgresql+asyncpg',host=config.pg.host,
   port=config.pg.port,username=config.pg.user,password=config.pg.password,database=database))
  spec=importlib.util.spec_from_file_location('questions','alembic/versions/041_human_questions.py')
  migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
  def migrate(connection,down=False):
   with Operations.context(MigrationContext.configure(connection)):
    (migration.downgrade if down else migration.upgrade)()
  async with engine.begin() as db:
   await db.execute(text('CREATE SCHEMA profile'))
   await db.execute(text('CREATE TABLE profile."user" (id uuid PRIMARY KEY)'))
   await db.execute(text('CREATE TABLE profile.chat_threads '
    '(thread_id uuid PRIMARY KEY,user_id uuid)'))
   await db.execute(text('CREATE TABLE profile.user_launch (id uuid PRIMARY KEY,user_id uuid,'
    'type text,status text,payload jsonb,celery_task_id text,created_at timestamptz DEFAULT now(),'
    'updated_at timestamptz DEFAULT now())'))
   await db.run_sync(migrate)
  count+=1
  factory=async_sessionmaker(engine,class_=AckSession,expire_on_commit=False)
  ack={'next':False}
  @asynccontextmanager
  async def context():
   async with factory() as db:
    db.info['lose_ack']=ack['next']; ack['next']=False
    yield db
  repository=HumanQuestionRepository(SimpleNamespace(get_session_context=context))
  async def stage_pause(item):
   async with context() as db:
    result=await repository.stage(item,session=db)
    await db.commit()
    return result
  user,thread=uuid.uuid4(),uuid.uuid4()
  async with engine.begin() as db:
   await db.execute(text('INSERT INTO profile."user" VALUES (:id)'),{'id':user})
   await db.execute(text('INSERT INTO profile.chat_threads VALUES (:thread,:user)'),
    {'thread':thread,'user':user})
  async def scalar(sql,**params):
   async with engine.connect() as db:
    return await db.scalar(text(sql),params)
  async def children(item):
   return await scalar('SELECT count(*) FROM profile.user_launch WHERE id=:id',
    id=item.resume_job_id)
  async def make(surface='ide',ttl=60,resumable=False):
   scope=QuestionScope(user,thread,uuid.uuid4()); attempt=uuid.uuid4()
   item=QuestionPause(scope,uuid.uuid4(),attempt,surface,uuid.uuid4(),'a'*64,
    QuestionPrompt.parse({'prompt':'Что создать?','choices':[
     {'id':'readme','label':'README'},{'id':'script','label':'Скрипт'}]}),
    time.time()+ttl,freeze_continuation({'messages':[{'role':'tool','content':'PRIVATE'}]}))
   if resumable:
    if surface=='pdf':
     item=replace(item,project_id=uuid.UUID(document_project_id(str(user),str(thread),'documents/test')))
    raw={'model':'test-model','tool_call_id':'question','messages':[
     {'role':'user','content':'PRIVATE-USER'},
     {'role':'assistant','content':None,'tool_calls':[
      {'id':'question','type':'function','function':{'name':'ask_user_question',
       'arguments':json.dumps(item.prompt.payload())}}]},
     {'role':'tool','tool_call_id':'question','content':'{"awaiting_user":true}'}]}
    item=replace(item,continuation_json=freeze_question_continuation(raw,item.prompt))
   async with engine.begin() as db:
    await db.execute(text("INSERT INTO profile.user_launch (id,user_id,type,status,payload) "
     "VALUES (:id,:user,'CHAT','PROCESSING',CAST(:payload AS jsonb))"),
     {'id':scope.source_job_id,'user':user,'payload':json.dumps({'thread_id':str(thread),
      '_execution_attempt_v1':str(attempt),'_accepted_turn_v1':{'fixture':True},
      'text':'PRIVATE-ORIGINAL'})})
   return item
  async def finish(item):
   async with engine.begin() as db:
     await db.execute(text("UPDATE profile.user_launch SET status='SUCCESS' WHERE id=:id"),
      {'id':item.scope.source_job_id})
  async def answer(item,intent=None,value=None,**changes):
   args=dict(intent_id=intent or uuid.uuid4(),answer=value or {'choice_id':'readme','text':None},
    surface=item.surface,project_id=item.project_id,revision=item.revision)
   return await repository.answer(item.scope,item.question_id,**{**args,**changes})
  async def rejected(awaitable,code):
   result=await awaitable
   assert isinstance(result,QuestionRefusal) and result.code==code
  stage='stage_and_identity'
  item=await make()
  view=await stage_pause(item)
  assert view['state']=='pending' and 'PRIVATE' not in json.dumps(view)
  assert await stage_pause(item)==view
  await rejected(stage_pause(replace(item,continuation_json='{}')),'human_question_conflict')
  await rejected(stage_pause(replace(item,question_id=uuid.uuid4())),'human_question_conflict')
  assert await repository.read(item.scope,item.question_id) is None
  await rejected(answer(item),'human_question_binding_changed')
  await finish(item)
  assert (await repository.read(item.scope,item.question_id))['state']=='pending'
  count+=1
  stage='owner_and_binding'
  for scope in (replace(item.scope,user_id=uuid.uuid4()),replace(item.scope,thread_id=uuid.uuid4()),
   replace(item.scope,source_job_id=uuid.uuid4())):
   assert await repository.read(scope,item.question_id) is None
   await rejected(repository.cancel(scope,item.question_id),'human_question_not_found')
  for changes in ({'project_id':uuid.uuid4()},{'surface':'pdf'},{'revision':'b'*64}):
   await rejected(answer(item,**changes),'human_question_binding_changed')
  count+=1
  stage='concurrent_answer'
  intent=uuid.uuid4()
  first,second=await asyncio.gather(answer(item,intent),answer(item,intent),return_exceptions=True)
  for result in (first,second):
   if isinstance(result,BaseException): raise result
  assert first==second and first['state']=='accepted'
  assert await children(item)==1
  child=await scalar('SELECT payload FROM profile.user_launch WHERE id=:id',id=item.resume_job_id)
  assert child['_human_question_dispatch_v1']=='pending'
  assert child['_human_question_parent_v1']['question_id']==str(item.question_id)
  assert 'PRIVATE' not in json.dumps(child)
  await rejected(answer(item,intent,{'choice_id':'script','text':None}),'human_question_conflict')
  await rejected(answer(item),'human_question_conflict')
  assert (await repository.cancel(item.scope,item.question_id))['state']=='accepted'
  count+=1
  stage='cancel_and_late_reply'
  cancelled=await make('pdf'); await stage_pause(cancelled); await finish(cancelled)
  assert (await repository.cancel(cancelled.scope,cancelled.question_id))['state']=='cancelled'
  assert (await answer(cancelled))['state']=='cancelled'
  assert (await stage_pause(cancelled))['state']=='cancelled'
  assert await children(cancelled)==0
  count+=1
  stage='actual_expiry'
  expired=await make(ttl=1); await stage_pause(expired); await finish(expired)
  limit=time.monotonic()+3
  while (await repository.read(expired.scope,expired.question_id))['state']!='expired':
   assert time.monotonic()<limit
   await asyncio.sleep(0.02)
  assert (await repository.read(expired.scope,expired.question_id))['state']=='expired'
  assert (await answer(expired))['state']=='expired'
  stored=await scalar('SELECT state FROM profile.human_question WHERE question_id=:id',
   id=expired.question_id)
  assert stored=='expired' and await children(expired)==0
  count+=1
  stage='rollback_on_child_conflict'
  collision=await make(); await stage_pause(collision); await finish(collision)
  async with engine.begin() as db:
   await db.execute(text('INSERT INTO profile.user_launch (id,user_id,type,status,payload) '
    "VALUES (:id,:user,'CHAT','NEW','{}'::jsonb)"),{'id':collision.resume_job_id,'user':user})
  try: await answer(collision)
  except RepositoryError: pass
  else: raise AssertionError('child_collision_must_rollback')
  assert (await repository.read(collision.scope,collision.question_id))['state']=='pending'
  count+=1
  stage='commit_loss'
  lost=await make(); await stage_pause(lost); await finish(lost)
  intent=uuid.uuid4(); ack['next']=True
  try: await answer(lost,intent)
  except RepositoryError: pass
  else: raise AssertionError('lost_commit_ack')
  assert (await repository.read(lost.scope,lost.question_id))['state']=='accepted'
  assert (await answer(lost,intent))['resume_job_id']==str(lost.resume_job_id)
  assert await children(lost)==1
  count+=1
  stage='cancel_answer_race'
  race=await make(); await stage_pause(race); await finish(race)
  results=await asyncio.gather(repository.cancel(race.scope,race.question_id),answer(race))
  current=await repository.read(race.scope,race.question_id)
  assert current['state'] in {'accepted','cancelled'}
  assert await children(race)==(1 if current['state']=='accepted' else 0)
  count+=1
  stage='migration_roundtrip'
  stage='expired_before_staging'
  old=await make(ttl=-1); assert (await stage_pause(old))['state']=='expired'
  await finish(old)
  assert (await answer(old))['state']=='expired' and await children(old)==0
  count+=1
  stage='atomic_question_and_accepted_facts'
  atomic=await make()
  async with engine.begin() as db:
   await db.execute(text("UPDATE profile.user_launch SET payload=payload-"
    "'_accepted_turn_v1' WHERE id=:id"),{'id':atomic.scope.source_job_id})
  async with context() as db:
   assert (await repository.stage(atomic,session=db))['state']=='pending'
   await db.execute(text('UPDATE profile.user_launch SET payload=payload || '
    'CAST(:accepted AS jsonb) WHERE id=:id'),{'id':atomic.scope.source_job_id,
    'accepted':json.dumps({'_accepted_turn_v1':{'fixture':True}})})
   assert await scalar('SELECT count(*) FROM profile.human_question WHERE question_id=:id',
    id=atomic.question_id)==0
   await db.rollback()
  assert await scalar('SELECT count(*) FROM profile.human_question WHERE question_id=:id',
   id=atomic.question_id)==0
  stored=await scalar('SELECT payload FROM profile.user_launch WHERE id=:id',
   id=atomic.scope.source_job_id)
  assert '_accepted_turn_v1' not in stored
  async with context() as db:
   assert (await repository.stage(atomic,session=db))['state']=='pending'
   await db.execute(text('UPDATE profile.user_launch SET payload=payload || '
    'CAST(:accepted AS jsonb) WHERE id=:id'),{'id':atomic.scope.source_job_id,
    'accepted':json.dumps({'_accepted_turn_v1':{'fixture':True}})})
   await db.commit()
  await finish(atomic)
  assert (await repository.read(atomic.scope,atomic.question_id))['state']=='pending'
  count+=1
  stage='private_resume_loading'
  for surface in ('ide','pdf'):
   resumed=await make(surface=surface,resumable=True)
   await stage_pause(resumed); await finish(resumed)
   target=({'repository_id':str(resumed.project_id),'generation':resumed.revision}
    if surface=='ide' else {'path':'documents/test','expected_revision':resumed.revision})
   intent=uuid.uuid4()
   view=await answer(resumed,intent=intent,resume_context=target)
   assert view['state']=='accepted' and 'PRIVATE' not in json.dumps(view)
   loaded=await repository.load_resume(user,thread,resumed.resume_job_id)
   assert isinstance(loaded,QuestionResume) and loaded.text=='PRIVATE-ORIGINAL'
   assert loaded.surface==surface and loaded.model=='test-model'
   assert json.loads(loaded.messages_json)[-1]['role']=='tool'
   assert json.loads(json.loads(loaded.messages_json)[-1]['content'])=={
    'answer':{'choice_id':'readme','text':None}}
   assert 'PRIVATE' not in repr(loaded)
   await rejected(repository.load_resume(uuid.uuid4(),thread,resumed.resume_job_id),
    'human_question_not_found')
   await rejected(repository.load_resume(user,uuid.uuid4(),resumed.resume_job_id),
    'human_question_not_found')
   assert (await answer(resumed,intent=intent,resume_context=target))==view
   assert await children(resumed)==1
   async with engine.begin() as db:
    await db.execute(text('UPDATE profile.user_launch SET payload=payload-:key WHERE id=:id'),
     {'id':resumed.resume_job_id,'key':RESUME_CONTEXT_KEY})
   await rejected(repository.load_resume(user,thread,resumed.resume_job_id),
    'human_question_unavailable')
   count+=1
  stage='concurrent_dispatch_claims'
  dispatches=HumanQuestionDispatchRepository(SimpleNamespace(get_session_context=context))
  async def admitted():
   item=await make(resumable=True); await stage_pause(item); await finish(item)
   target={'repository_id':str(item.project_id),'generation':item.revision}
   planned=await repository.plan_answer(item.scope,item.question_id,
    {'choice_id':'readme','text':None},target)
   await answer(item,resume_context=target,cost=QuestionCost.quote(planned,1,required=False))
   return item
  async def expire_claim(item):
   async with engine.begin() as db:
    await db.execute(text("UPDATE profile.user_launch SET payload=payload || "
     "jsonb_build_object('_human_question_dispatch_after_v1',now()-interval '1 minute') "
     "WHERE id=:id"),{'id':item.resume_job_id})
  one,two=await admitted(),await admitted()
  claimed=await asyncio.gather(dispatches.claim_pending(),dispatches.claim_pending(),
   return_exceptions=True)
  for batch in claimed:
   if isinstance(batch,BaseException): raise batch
  claims=[claim for batch in claimed for claim in batch]
  assert len(claims)==2
  assert {claim.job_id for claim in claims}=={one.resume_job_id,two.resume_job_id}
  assert all(claim.task_id==str(claim.job_id) for claim in claims)
  assert await dispatches.claim_pending()==()
  assert not await dispatches.acknowledge(replace(claims[0],claim_id=uuid.uuid4()))
  assert await dispatches.acknowledge(claims[0])
  assert not await dispatches.acknowledge(claims[0])
  count+=1
  stage='unknown_broker_delivery'
  waiting=one if one.resume_job_id==claims[1].job_id else two
  await expire_claim(waiting)
  class Queue:
   def __init__(self): self.calls=[]; self.lose=True
   def enqueue_agent_message(self,**payload):
    self.calls.append(payload)
    if self.lose: raise RuntimeError('PRIVATE-UNKNOWN-ACK')
    return payload['_delivery_task_id']
  queue=Queue()
  result=await dispatch_question_children(dispatches,queue,enabled=True)
  assert result=={'claimed':1,'acknowledged':0,'deferred':1}
  assert not await dispatches.acknowledge(claims[1])
  assert (await dispatch_question_children(dispatches,queue,enabled=True))['claimed']==0
  assert len(queue.calls)==1
  await expire_claim(waiting); queue.lose=False
  assert (await dispatch_question_children(dispatches,queue,enabled=True))=={
   'claimed':1,'acknowledged':1,'deferred':0}
  assert queue.calls[0]==queue.calls[1]
  assert queue.calls[0]['job_id']==str(waiting.resume_job_id)
  assert queue.calls[0]['text']=='' and 'PRIVATE' not in json.dumps(queue.calls)
  assert await children(waiting)==1
  count+=1
  stage='delivered_but_never_started_child_is_reconciled'
  # Broker ACK alone does not prove that hydration/first execution ever ran.
  # Only NEW + no execution attempt can be redelivered under a fresh lease.
  before=len(queue.calls)
  assert (await dispatch_question_children(dispatches,queue,enabled=True))['claimed']==0
  await expire_claim(waiting)
  recovered=await dispatch_question_children(dispatches,queue,enabled=True)
  assert recovered=={'claimed':1,'acknowledged':1,'deferred':0}
  assert len(queue.calls)==before+1 and queue.calls[-1]==queue.calls[-2]
  assert await children(waiting)==1
  jobs=JobRepository(SimpleNamespace(get_session_context=context))
  async with context() as db:
   assert await jobs.claim_chat_execution(waiting.resume_job_id,user,str(thread),
    str(uuid.uuid4()),session=db)
   await db.commit()
  await expire_claim(waiting)
  assert (await dispatch_question_children(dispatches,queue,enabled=True))['claimed']==0
  assert len(queue.calls)==before+1
  count+=1
  stage='unknown_dispatch_commit'
  lost=await admitted(); before=len(queue.calls); ack['next']=True
  try: await dispatch_question_children(dispatches,queue,enabled=True)
  except RepositoryError: pass
  else: raise AssertionError('lost_commit_must_not_dispatch')
  assert len(queue.calls)==before
  assert (await dispatch_question_children(dispatches,queue,enabled=True))['claimed']==0
  await expire_claim(lost)
  assert (await dispatch_question_children(dispatches,queue,enabled=True))['acknowledged']==1
  count+=1
  stage='cancelled_and_started_children_not_dispatched'
  cancelled,started=await admitted(),await admitted()
  jobs=JobRepository(SimpleNamespace(get_session_context=context))
  async with context() as db:
   assert await jobs.request_chat_cancel(cancelled.resume_job_id,user,session=db)
   await db.commit()
  async def claim_execution(item):
   async with context() as db:
    result=await jobs.claim_chat_execution(item.resume_job_id,user,str(thread),
     str(uuid.uuid4()),session=db)
    await db.commit(); return result
  first,second=await asyncio.gather(claim_execution(started),claim_execution(started),
   return_exceptions=True)
  for result in (first,second):
   if isinstance(result,BaseException): raise result
  assert sorted([first,second])==[False,True]
  assert await dispatches.claim_pending()==()
  assert await children(cancelled)==1 and await children(started)==1
  count+=1
  stage='pending_cost_cannot_dispatch'
  costs=HumanQuestionCostRepository(SimpleNamespace(get_session_context=context))
  async def costly():
   item=await make(resumable=True); await stage_pause(item); await finish(item)
   target={'repository_id':str(item.project_id),'generation':item.revision}
   planned=await repository.plan_answer(item.scope,item.question_id,
    {'choice_id':'readme','text':None},target)
   cost=QuestionCost.quote(planned,100,required=True)
   await answer(item,resume_context=target,cost=cost)
   return item,planned,cost
  item,planned,cost=await costly()
  public=await costs.read(item.scope,item.question_id)
  assert public['state']=='pending' and public['estimated_credits']==100
  assert set(public)=={'offer_id','state','estimated_credits','expires_at'}
  assert 'PRIVATE' not in json.dumps(public) and cost.binding not in json.dumps(public)
  assert await dispatches.claim_pending()==()
  await rejected(costs.read(replace(item.scope,user_id=uuid.uuid4()),item.question_id),
   'human_question_not_found')
  await rejected(costs.decide(item.scope,item.question_id,uuid.uuid4(),'accept'),
   'human_question_conflict')
  count+=1
  stage='same_cost_accept_is_idempotent'
  accepted=await asyncio.gather(costs.decide(item.scope,item.question_id,cost.offer_id,'accept'),
   costs.decide(item.scope,item.question_id,cost.offer_id,'accept'))
  assert accepted[0]==accepted[1] and accepted[0]['state']=='accepted'
  await rejected(costs.decide(item.scope,item.question_id,cost.offer_id,'decline'),
   'human_question_conflict')
  dispatched=await dispatches.claim_pending()
  assert len(dispatched)==1 and dispatched[0].job_id==item.resume_job_id
  assert await children(item)==1
  async with context() as db:
   assert await jobs.claim_chat_execution(item.resume_job_id,user,str(thread),
    str(uuid.uuid4()),session=db)
   await db.commit()
  accepted=await costs.decide(item.scope,item.question_id,cost.offer_id,'accept')
  assert accepted['state']=='accepted'
  assert await dispatches.claim_pending()==()
  count+=1
  stage='cost_decline_never_dispatches'
  item,planned,cost=await costly()
  declined=await costs.decide(item.scope,item.question_id,cost.offer_id,'decline')
  replay=await costs.decide(item.scope,item.question_id,cost.offer_id,'decline')
  assert declined==replay and declined['state']=='declined'
  status=await scalar('SELECT status FROM profile.user_launch WHERE id=:id',id=item.resume_job_id)
  assert status=='FAILURE'
  assert await dispatches.claim_pending()==() and await children(item)==1
  count+=1
  stage='expired_cost_refresh_and_unknown_accept_commit'
  item,planned,cost=await costly()
  # Expire only this private quote in the isolated fixture, not a runtime policy.
  async with engine.begin() as db:
   await db.execute(text("UPDATE profile.user_launch SET payload=jsonb_set(payload,"
    "'{_human_question_cost_v1,expires_at}',to_jsonb(extract(epoch from now())::float8-1)) "
    "WHERE id=:id"),{'id':item.resume_job_id})
  assert (await costs.read(item.scope,item.question_id))['state']=='expired'
  expired=await costs.decide(item.scope,item.question_id,cost.offer_id,'accept')
  assert expired['state']=='expired'
  assert await dispatches.claim_pending()==()
  replacement=QuestionCost.quote(planned,120,required=True)
  fresh=await costs.decide(item.scope,item.question_id,cost.offer_id,'refresh',
   replacement=replacement)
  assert fresh['state']=='pending' and fresh['estimated_credits']==120
  replay=await costs.decide(item.scope,item.question_id,cost.offer_id,'refresh',
   replacement=replacement)
  assert fresh==replay
  ack['next']=True
  try: await costs.decide(item.scope,item.question_id,uuid.UUID(fresh['offer_id']),'accept')
  except RepositoryError: pass
  else: raise AssertionError('lost_cost_commit_ack_expected')
  assert (await costs.read(item.scope,item.question_id))['state']=='accepted'
  recovered=await costs.decide(item.scope,item.question_id,uuid.UUID(fresh['offer_id']),'accept')
  assert recovered['state']=='accepted'
  assert await children(item)==1
  async with context() as db:
   assert await jobs.request_chat_cancel(item.resume_job_id,user,session=db)
   await db.commit()
  assert await dispatches.claim_pending()==()
  count+=1
  stage='cost_accept_decline_race_and_cancelled_quote'
  item,planned,cost=await costly()
  race=await asyncio.gather(costs.decide(item.scope,item.question_id,cost.offer_id,'accept'),
   costs.decide(item.scope,item.question_id,cost.offer_id,'decline'))
  assert sum(isinstance(result,QuestionRefusal) for result in race)==1
  winner=next(result for result in race if not isinstance(result,QuestionRefusal))
  assert winner['state'] in {'accepted','declined'} and await children(item)==1
  stored=await scalar('SELECT payload FROM profile.user_launch WHERE id=:id',id=item.resume_job_id)
  assert stored[COST_KEY]['decided_at']>0
  async with context() as db:
   await jobs.request_chat_cancel(item.resume_job_id,user,session=db)
   await db.commit()
  item,planned,cost=await costly()
  async with context() as db:
   assert await jobs.request_chat_cancel(item.resume_job_id,user,session=db)
   await db.commit()
  assert (await costs.read(item.scope,item.question_id))['state']=='cancelled'
  await rejected(costs.decide(item.scope,item.question_id,cost.offer_id,'accept'),
   'human_question_conflict')
  assert await dispatches.claim_pending()==()
  count+=1
  stage='stop_unstarted_accepted_quote_is_terminal_without_dispatch'
  item,planned,cost=await costly()
  await costs.decide(item.scope,item.question_id,cost.offer_id,'accept')
  assert await jobs.cancel_unstarted_question(item.resume_job_id,user)
  status=await scalar('SELECT status FROM profile.user_launch WHERE id=:id',
   id=item.resume_job_id)
  assert status=='FAILURE'
  assert (await costs.read(item.scope,item.question_id))['state']=='cancelled'
  assert await dispatches.claim_pending()==()
  assert not await jobs.cancel_unstarted_question(item.resume_job_id,user)
  count+=1
  stage='lost_stop_commit_ack_recovers_same_child'
  item,planned,cost=await costly()
  ack['next']=True
  try: await jobs.cancel_unstarted_question(item.resume_job_id,user)
  except RepositoryError: pass
  else: raise AssertionError('lost_stop_commit_ack_expected')
  assert (await costs.read(item.scope,item.question_id))['state']=='cancelled'
  status=await scalar('SELECT status FROM profile.user_launch WHERE id=:id',
   id=item.resume_job_id)
  assert status=='FAILURE'
  assert not await jobs.cancel_unstarted_question(item.resume_job_id,user)
  count+=1
  stage='cost_accept_races_unstarted_stop'
  item,planned,cost=await costly()
  decision,stopped=await asyncio.gather(
   costs.decide(item.scope,item.question_id,cost.offer_id,'accept'),
   jobs.cancel_unstarted_question(item.resume_job_id,user))
  assert stopped and (isinstance(decision,QuestionRefusal) or decision['state']=='accepted')
  assert (await costs.read(item.scope,item.question_id))['state']=='cancelled'
  assert await dispatches.claim_pending()==()
  count+=1
  stage='first_execution_races_unstarted_stop'
  item,planned,cost=await costly()
  await costs.decide(item.scope,item.question_id,cost.offer_id,'accept')
  async def begin_child():
   async with context() as db:
    started=await jobs.claim_chat_execution(item.resume_job_id,user,str(thread),
     str(uuid.uuid4()),session=db)
    await db.commit(); return started
  started,stopped=await asyncio.gather(begin_child(),
   jobs.cancel_unstarted_question(item.resume_job_id,user))
  assert started != stopped
  if started:
   assert (await costs.read(item.scope,item.question_id))['state']=='accepted'
  else:
   assert (await costs.read(item.scope,item.question_id))['state']=='cancelled'
  assert await dispatches.claim_pending()==()
  count+=1
  stage='foreign_owner_cannot_stop_question_child'
  item,planned,cost=await costly()
  assert not await jobs.cancel_unstarted_question(item.resume_job_id,uuid.uuid4())
  assert (await costs.read(item.scope,item.question_id))['state']=='pending'
  assert await jobs.cancel_unstarted_question(item.resume_job_id,user)
  count+=1
  stage='migration_roundtrip'
  async with engine.begin() as db:
   await db.run_sync(lambda connection:migrate(connection,True))
   assert await db.scalar(text("SELECT to_regclass('profile.human_question')")) is None
   await db.run_sync(migrate)
   assert await db.scalar(text('SELECT count(*) FROM profile.human_question'))==0
   await db.run_sync(lambda connection:migrate(connection,True))
  count+=1
 finally:
  if engine is not None: await engine.dispose()
  if created:
   await admin.execute('DROP DATABASE "'+database+'"')
   assert not await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',database)
  await admin.close()
 print(json.dumps({'cases':count,'fixture_removed':True,'source_parity':True,'runtime_allocations':0,'queue_dispatches':0}))
try: asyncio.run(main())
except BaseException as error:
 print(json.dumps({'status':'failed','stage':stage,'error':type(error).__name__}))
 raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_HUMAN_QUESTIONS") != "1", reason="isolated question journal opt-in"
)
def test_postgres_question_answer_replay_expiry_and_commit_loss():
    root = Path(__file__).resolve().parents[1]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in FILES}
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", PROBE],
        input=json.dumps({"files": files}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        pytest.fail("human_question_probe_output_invalid")
    assert result.returncode == 0, f"human_question_probe_failed:{outcome}"
    assert outcome == {
        "cases": 29,
        "fixture_removed": True,
        "source_parity": True,
        "runtime_allocations": 0,
        "queue_dispatches": 0,
    }
