"""Opt-in restore claim/swap proof in a disposable database, never dev migration."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

FILES = (
    "alembic/versions/043_harness_state.py",
    "alembic/versions/046_ide_command_operations.py",
    "service/services/chat/persistence/harness/commands/gate.py",
    "alembic/versions/032_ide_repositories.py",
    "alembic/versions/033_ide_runtime_claims.py",
    "alembic/versions/034_ide_checkpoint_revisions.py",
    "alembic/versions/039_ide_restore_journal.py",
    "alembic/versions/040_ide_checkpoint_accounting.py",
    "alembic/versions/042_ide_checkpoint_orphan_cleanup.py",
    "service/services/chat/domain/ide/checkpoints/blob.py",
    "service/services/chat/domain/ide/checkpoints/restore.py",
    "service/services/chat/domain/ide/runtime.py",
    "service/services/chat/persistence/ide/checkpoints/restore.py",
    "service/services/chat/persistence/ide/checkpoints/repository.py",
    "service/services/chat/persistence/ide/checkpoints/retention.py",
    "service/services/chat/persistence/ide/checkpoints/orphans.py",
    "service/services/chat/application/ide/checkpoints/orphans.py",
    "service/services/chat/application/ide/checkpoints/restore.py",
    "service/infrastructure/ide/transports/capture.py",
    "service/services/chat/domain/ide/checkpoints/revision.py",
    "service/services/chat/domain/ide/checkpoints/budget.py",
    "service/services/chat/application/ide/checkpoints/service.py",
    "service/services/chat/application/ide/checkpoints/retention.py",
    "service/infrastructure/ide/checkpoint_storage.py",
    "service/infrastructure/storage/local_file_storage.py",
    "service/infrastructure/storage/bounded_download.py",
    "service/infrastructure/storage/stream_upload_contract.py",
    "service/infrastructure/storage/identity.py",
    "service/services/chat/persistence/ide/runtime.py",
    "service/shared/repositories/decorators/session_processor.py",
)
PROBE = r"""
import asyncio, hashlib, importlib.util, io, json, logging, re, sys, tempfile, uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import asyncpg
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from service.settings import config
from service.services.chat.domain.ide.runtime import (
 RepositoryScope, RuntimeAttempt, RuntimeObservation, WorkspaceBinding,
)
from service.services.chat.persistence.ide.checkpoints.restore import IdeRestoreRepository
from service.services.chat.persistence.ide.checkpoints.retention import (
 IdeCheckpointRetentionRepository,
)
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.shared.repositories.exceptions import RepositoryError
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.checkpoints.retention import (
 IdeCheckpointRetentionService,
)
from service.services.chat.application.ide.checkpoints.orphans import IdeCheckpointOrphanService
from service.services.chat.application.ide.checkpoints.restore import IdeRestoreService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.persistence.ide.checkpoints.orphans import IdeCheckpointOrphanRepository
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
logging.disable(logging.CRITICAL)
stage='source_parity'

class AckSession(AsyncSession):
 async def commit(self):
  mode=self.info.pop('lose_ack',None)
  if mode=='before': raise OperationalError('PRIVATE',{},Exception('PRIVATE'))
  await super().commit()
  if mode=='after': raise OperationalError('PRIVATE',{},Exception('PRIVATE'))

async def main():
 global stage
 files=probe_input['files']
 assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
  for path,digest in files.items())
 for path in files:
  if path.startswith('service/'):
   module=__import__(path[:-3].replace('/','.'),fromlist=['__file__'])
   assert Path(module.__file__).resolve()==Path(path).resolve()
 assert config.pg.host=='postgres'
 database='gpthub_ide_restore_'+uuid.uuid4().hex[:24]
 assert re.fullmatch(r'gpthub_ide_restore_[0-9a-f]{24}',database)
 admin=await asyncpg.connect(host=config.pg.host,port=config.pg.port,user=config.pg.user,
  password=config.pg.password,database=config.pg.db,timeout=5)
 engine=None; created=False; count=0
 try:
  stage='fixture_database'
  await admin.execute('CREATE DATABASE "'+database+'"'); created=True
  engine=create_async_engine(URL.create('postgresql+asyncpg',host=config.pg.host,
   port=config.pg.port,username=config.pg.user,password=config.pg.password,database=database),echo=False)
  migrations=[]
  for number in ('032_ide_repositories','033_ide_runtime_claims','034_ide_checkpoint_revisions',
   '039_ide_restore_journal','040_ide_checkpoint_accounting','042_ide_checkpoint_orphan_cleanup',
   '043_harness_state','046_ide_command_operations'):
   spec=importlib.util.spec_from_file_location(number,'alembic/versions/'+number+'.py')
   module=importlib.util.module_from_spec(spec)
   spec.loader.exec_module(module); migrations.append(module)
  def migrate(connection,down=False):
   with Operations.context(MigrationContext.configure(connection)):
    for migration in (reversed(migrations) if down else migrations):
     (migration.downgrade if down else migration.upgrade)()
  stage='migration_upgrade'
  async with engine.begin() as db:
   await db.execute(text('CREATE SCHEMA profile'))
   await db.execute(text('CREATE TABLE profile."user" (id uuid PRIMARY KEY)'))
   await db.execute(text('CREATE TABLE profile.chat_threads '
    '(thread_id uuid UNIQUE NOT NULL,user_id uuid)'))
   await db.execute(text('CREATE TABLE profile.user_launch (id uuid PRIMARY KEY)'))
   await db.run_sync(migrate)
   index=await db.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname='profile' "
    "AND indexname='ix_ide_cp_settled_cleanup'"))
   assert 'storage_namespace, repository_id, checkpoint_id' in index
   assert 'upload_settled_at IS NOT NULL' in index and 'collected_at IS NULL' in index
  count+=1
  factory=async_sessionmaker(engine,class_=AckSession,expire_on_commit=False)
  ack={'next':None}
  @asynccontextmanager
  async def context():
   async with factory() as db:
    db.info['lose_ack']=ack['next']; ack['next']=None
    yield db
  connector=SimpleNamespace(get_session_context=context)
  records=IdeRestoreRepository(connector); runtimes=IdeRuntimeRepository(connector)
  owner,other,thread,sibling=[uuid.uuid4() for _ in range(4)]
  async with engine.begin() as db:
   for uid in (owner,other):
    await db.execute(text('INSERT INTO profile."user" VALUES (:id)'),{'id':uid})
   for tid in (thread,sibling):
    await db.execute(text('INSERT INTO profile.chat_threads VALUES (:id,:owner)'),
     {'id':tid,'owner':owner})
  async def new_repo(live=False,published=True):
   scope=RepositoryScope(thread,owner,uuid.uuid4()); allocation,checkpoint=uuid.uuid4(),uuid.uuid4()
   async with engine.begin() as db:
    await db.execute(text('INSERT INTO profile.ide_repository '
     '(repository_id,thread_id,user_id,creation_intent_id,name) '
     "VALUES (:repository_id,:thread_id,:user_id,:creation,'Fixture')"),
     {**scope.params(),'creation':uuid.uuid4()})
    await db.execute(text('INSERT INTO profile.ide_repository_runtime '
     '(repository_id,allocation_id,expires_at,state) VALUES (:repository_id,:allocation,'
     "floor(extract(epoch FROM clock_timestamp()))::bigint+:ttl,'ready')"),
     {**scope.params(),'allocation':allocation,'ttl':600 if live else -1})
    await db.execute(text('INSERT INTO profile.ide_checkpoint_intent '
     '(repository_id,checkpoint_id,thread_id,user_id,allocation_id,sha256,size,'
     'storage_namespace,state,published_at) '
     'VALUES (:repository_id,:checkpoint,:thread_id,:user_id,:allocation,:sha,10,:namespace,'
     ':state,CASE WHEN :published THEN clock_timestamp() ELSE NULL END)'),
     {**scope.params(),'checkpoint':checkpoint,'allocation':allocation,'sha':'a'*64,
      'namespace':'b'*64,'state':'published' if published else 'pending','published':published})
   return scope,allocation,checkpoint
  async def claim(scope,allocation,checkpoint,restore_id=None,ttl=300):
   return await records.reserve(scope,restore_id or uuid.uuid4(),checkpoint,allocation,ttl_sec=ttl)
  stage='ownership'
  scope,allocation,checkpoint=await new_repo()
  for changes in ({'user_id':other},{'thread_id':sibling},{'repository_id':uuid.uuid4()}):
   foreign=replace(scope,**changes)
   assert (await claim(foreign,allocation,checkpoint)).failure=='missing'
  count+=1
  stage='admission'
  live_scope,live_allocation,live_checkpoint=await new_repo(live=True)
  assert (await claim(live_scope,live_allocation,live_checkpoint)).failure=='runtime_not_expired'
  assert (await claim(scope,uuid.uuid4(),checkpoint)).failure=='runtime_not_expired'
  pending_scope,pending_allocation,pending_checkpoint=await new_repo(published=False)
  denied=await claim(pending_scope,pending_allocation,pending_checkpoint)
  assert denied.failure=='checkpoint_not_published'
  count+=1
  stage='parallel_exact_claim'
  restore_id=uuid.uuid4()
  claims=await asyncio.gather(*(claim(scope,allocation,checkpoint,restore_id) for _ in range(16)))
  assert sum(item.dispatch for item in claims)==1
  original=claims[0].record
  assert all(item.record==original for item in claims)
  assert original.allocation_id!=allocation
  old=await runtimes.get_owned(scope)
  assert old.allocation_id==allocation and old.expires_at<original.expires_at
  count+=1
  stage='competing_intents'
  competitors=await asyncio.gather(*(claim(scope,allocation,checkpoint) for _ in range(8)))
  assert all(item.failure=='restore_pending' and not item.dispatch for item in competitors)
  replay=await claim(scope,allocation,checkpoint,restore_id,ttl=600)
  assert replay.record==original and not replay.dispatch
  count+=1
  stage='unverified_cannot_publish'
  for value in (False,1):
   assert await records.publish(scope,restore_id,verified=value)==original
   assert await runtimes.get_owned(scope)==old
  count+=1
  stage='atomic_publish_and_stale_observation'
  current=await records.publish(scope,restore_id,verified=True)
  assert current.state=='published'
  new=await runtimes.get_owned(scope)
  assert new.allocation_id==original.allocation_id and new.expires_at==original.expires_at
  assert new.state=='ready' and not new.retry_allowed and new.observation==old.observation+1
  observed=await runtimes.record_observation(scope,old,'expired')
  assert observed==new
  assert await records.publish(scope,restore_id,verified=True)==current
  assert (await claim(scope,allocation,checkpoint,restore_id)).record==current
  assert await runtimes.get_owned(scope)==new
  count+=1
  stage='expired_target'
  exp_scope,exp_allocation,exp_checkpoint=await new_repo()
  pending=(await claim(exp_scope,exp_allocation,exp_checkpoint)).record
  async with engine.begin() as db:
   await db.execute(text('UPDATE profile.ide_restore_intent SET expires_at=1 '
    'WHERE repository_id=:repository_id'),exp_scope.params())
  assert (await records.publish(exp_scope,pending.restore_id,verified=True)).state=='expired'
  assert (await runtimes.get_owned(exp_scope)).allocation_id==exp_allocation
  fresh=await claim(exp_scope,exp_allocation,exp_checkpoint)
  assert fresh.dispatch and fresh.record.allocation_id!=pending.allocation_id
  replay=await claim(exp_scope,exp_allocation,exp_checkpoint,pending.restore_id)
  assert replay.record.state=='expired'
  count+=1
  stage='changed_generation'
  changed_scope,changed_allocation,changed_checkpoint=await new_repo()
  pending=(await claim(changed_scope,changed_allocation,changed_checkpoint)).record
  replacement=uuid.uuid4()
  async with engine.begin() as db:
   await db.execute(text('UPDATE profile.ide_repository_runtime SET allocation_id=:replacement,'
    "expires_at=floor(extract(epoch FROM clock_timestamp()))::bigint+600,state='ready' "
    'WHERE repository_id=:repository_id'),{**changed_scope.params(),'replacement':replacement})
  assert (await records.publish(changed_scope,pending.restore_id,verified=True)).state=='conflict'
  assert (await runtimes.get_owned(changed_scope)).allocation_id==replacement
  count+=1
  stage='claim_commit_loss'
  for mode in ('before','after'):
   ack_scope,ack_allocation,ack_checkpoint=await new_repo(); rid=uuid.uuid4()
   ack['next']=mode
   try: await claim(ack_scope,ack_allocation,ack_checkpoint,rid)
   except RepositoryError: pass
   else: raise AssertionError('lost_ack_not_signalled')
   restored=await records.get_owned(ack_scope,rid)
   assert (restored is None) if mode=='before' else restored.state=='pending'
   assert (await runtimes.get_owned(ack_scope)).allocation_id==ack_allocation
  count+=1
  stage='publish_commit_loss'
  for mode in ('before','after'):
   ack_scope,ack_allocation,ack_checkpoint=await new_repo()
   pending=(await claim(ack_scope,ack_allocation,ack_checkpoint)).record
   ack['next']=mode
   try: await records.publish(ack_scope,pending.restore_id,verified=True)
   except RepositoryError: pass
   else: raise AssertionError('publish_ack_not_signalled')
   observed=await records.get_owned(ack_scope,pending.restore_id)
   actual=await runtimes.get_owned(ack_scope)
   assert observed.state==('pending' if mode=='before' else 'published')
   assert actual.allocation_id==(ack_allocation if mode=='before' else pending.allocation_id)
   assert (await records.publish(ack_scope,pending.restore_id,verified=True)).state=='published'
   assert (await runtimes.get_owned(ack_scope)).allocation_id==pending.allocation_id
  count+=1
  stage='active_checkpoint_pin_and_terminal_tombstone'
  try:
   async with engine.begin() as db:
    await db.execute(text('DELETE FROM profile.ide_checkpoint_intent '
     'WHERE repository_id=:repository_id AND checkpoint_id=:checkpoint_id'),
     {**exp_scope.params(),'checkpoint_id':exp_checkpoint})
  except IntegrityError: pass
  else: raise AssertionError('restore_snapshot_fk_missing')
  async with engine.begin() as db:
   await db.execute(text('DELETE FROM profile.ide_checkpoint_intent '
    'WHERE repository_id=:repository_id AND checkpoint_id=:checkpoint_id'),
    {**scope.params(),'checkpoint_id':checkpoint})
  assert await records.get_owned(scope,restore_id)==current
  assert (await claim(scope,allocation,checkpoint,restore_id)).record==current
  count+=1
  stage='history_retention_and_restore_pin'
  history_scope,history_allocation,history_head=await new_repo()
  history=IdeCheckpointRetentionRepository(connector)
  extra=[uuid.uuid4() for _ in range(12)]
  async with engine.begin() as db:
   await db.execute(text('INSERT INTO profile.ide_repository_head VALUES (:repository_id,:head)'),
    {**history_scope.params(),'head':history_head})
   for index,checkpoint_id in enumerate(extra):
    await db.execute(text('INSERT INTO profile.ide_checkpoint_intent '
     '(repository_id,checkpoint_id,thread_id,user_id,allocation_id,sha256,size,'
     'storage_namespace,state,published_at) SELECT repository_id,:new_id,thread_id,user_id,'
     "allocation_id,sha256,size,storage_namespace,'published',"
     "clock_timestamp()+(:rank * interval '1 second') FROM profile.ide_checkpoint_intent "
     'WHERE repository_id=:repository_id AND checkpoint_id=:head'),
     {**history_scope.params(),'new_id':checkpoint_id,'head':history_head,'rank':index+1})
   await db.execute(text('UPDATE profile.ide_checkpoint_intent '
    'SET upload_settled_at=clock_timestamp() WHERE repository_id=:repository_id'),
    history_scope.params())
  pinned=(await claim(history_scope,history_allocation,extra[0])).record
  assert (history_scope,history_head) in await history.maintenance_scopes(
   storage_namespace='b'*64)
  retired=await history.retire_history(history_scope,after_checkpoint_id=history_head,
   storage_namespace='b'*64)
  assert {item.intent.blob.checkpoint_id for item in retired}=={extra[1]}
  async with engine.connect() as db:
   assert await db.scalar(text("SELECT count(*) FROM profile.ide_checkpoint_intent "
    "WHERE repository_id=:repository_id AND state='published'"),history_scope.params())==12
  for foreign in (replace(history_scope,user_id=other),replace(history_scope,thread_id=sibling)):
   assert await history.retire_history(foreign,after_checkpoint_id=history_head,
    storage_namespace='b'*64)==[]
  assert await history.retire_history(history_scope,after_checkpoint_id=extra[1],
   storage_namespace='b'*64)==[]
  assert (await records.publish(history_scope,pinned.restore_id,verified=True)).state=='published'
  retired=await history.retire_history(history_scope,after_checkpoint_id=history_head,
   storage_namespace='b'*64)
  assert {item.intent.blob.checkpoint_id for item in retired}=={extra[0],extra[1]}
  await history.acknowledge_discard(retired[0].intent)
  rotated=await history.retire_history(history_scope,after_checkpoint_id=history_head,
   storage_namespace='b'*64)
  assert rotated[0].intent.blob.checkpoint_id!=retired[0].intent.blob.checkpoint_id
  async with engine.connect() as db:
   assert await db.scalar(text("SELECT count(*) FROM profile.ide_checkpoint_intent "
    "WHERE repository_id=:repository_id AND state='published'"),history_scope.params())==11
  assert (await claim(history_scope,pinned.allocation_id,extra[0])).failure=='runtime_not_expired'
  count+=1
  stage='atomic_user_storage_budget'
  budget_repo=IdeCheckpointRepository(connector)
  qa,aa,_=await new_repo(live=True)
  qb,ab,_=await new_repo(live=True)
  async with engine.connect() as db:
   used=int(await db.scalar(text('SELECT coalesce(sum(size),0) '
    'FROM profile.ide_checkpoint_intent WHERE user_id=:user_id AND collected_at IS NULL'),
    {'user_id':owner}))
  limits=CheckpointStorageBudget(used+15,10,4)
  ia=CheckpointIntent(CheckpointBlob(qa,uuid.uuid4(),'a'*64,10),aa,None,'b'*64)
  ib=CheckpointIntent(CheckpointBlob(qb,uuid.uuid4(),'a'*64,10),ab,None,'b'*64)
  admitted=await asyncio.gather(*(budget_repo.reserve(i,budget=limits) for i in (ia,ib)))
  assert sum(item.dispatch for item in admitted)==1
  assert sum(item.failure=='quota' for item in admitted)==1
  winner=ia if admitted[0].dispatch else ib
  assert not (await budget_repo.reserve(winner,budget=limits)).dispatch
  another=replace(winner,blob=replace(winner.blob,checkpoint_id=uuid.uuid4()))
  assert (await budget_repo.reserve(another,
   budget=CheckpointStorageBudget(used+100,10,1))).failure=='pending'
  row,allowed=await budget_repo.abandon_pending(winner.blob.scope,winner.blob.checkpoint_id)
  assert not allowed and row.state=='pending' and not row.upload_settled
  wrong=replace(winner,blob=replace(winner.blob,sha256='c'*64))
  assert not (await budget_repo.mark_upload_settled(wrong)).upload_settled
  revoked,allowed=await budget_repo.revoke_pending(winner.blob.scope,winner.blob.checkpoint_id)
  assert (allowed and revoked.state=='retired'
   and not revoked.upload_settled and not revoked.collected)
  assert await budget_repo.accounted_bytes(owner)==used+10
  assert (await budget_repo.reserve(another,
   budget=CheckpointStorageBudget(used+100,10,1))).failure=='pending'
  assert not (await budget_repo.reserve(winner,budget=limits)).dispatch
  late=await budget_repo.publish(winner.blob.scope,winner.blob.checkpoint_id,
   verified=True,historical=True)
  assert late.state=='retired' and not late.is_current
  receipt=await budget_repo.mark_upload_settled(winner)
  assert receipt.upload_settled and not receipt.collected
  rows=await budget_repo.inventory(winner.blob.scope)
  assert any(row['checkpoint_id']==winner.blob.checkpoint_id for row in rows)
  assert all('sha256' not in row and 'storage_namespace' not in row for row in rows)
  assert await budget_repo.inventory(replace(winner.blob.scope,user_id=other)) is None
  assert await budget_repo.accounted_bytes(owner)==used+10
  cancelled,allowed=await budget_repo.abandon_pending(winner.blob.scope,winner.blob.checkpoint_id)
  assert allowed and cancelled.state=='retired' and cancelled.upload_settled
  cleanup_rows=await budget_repo.inventory(winner.blob.scope)
  assert any(row['checkpoint_id']==winner.blob.checkpoint_id and row['state']=='retired'
   and row['upload_settled_at'] is not None for row in cleanup_rows)
  assert await history.acknowledge_discard(cancelled.intent)
  assert not any(row['checkpoint_id']==winner.blob.checkpoint_id
   for row in await budget_repo.inventory(winner.blob.scope))
  assert await budget_repo.accounted_bytes(owner)==used
  cancelled,allowed=await budget_repo.abandon_pending(winner.blob.scope,winner.blob.checkpoint_id)
  assert allowed and cancelled.collected
  kept,allowed=await budget_repo.abandon_pending(history_scope,history_head)
  assert not allowed and kept.state=='published' and kept.is_current
  assert await records.latest_owned(history_scope) is not None
  assert await records.latest_owned(replace(history_scope,user_id=other)) is None
  assert await records.latest_owned(qa) is None
  count+=1
  stage='verified_historical_versions_never_advance_head'
  with tempfile.TemporaryDirectory(prefix='ide-historical-') as folder:
   storage=IdeCheckpointStorage(LocalFileStorage(folder),max_bytes=100)
   technical=CheckpointStorageBudget(1000000,100,4)
   checkpoints=IdeCheckpointService(budget_repo,storage,budget=technical,historical=True,
    retention=IdeCheckpointRetentionService(history,storage))
   for late in ('expired','newer_head'):
    saved_scope,saved_allocation,older=await new_repo(live=True)
    body=b'snapshot-'+late.encode()
    saved_intent=CheckpointIntent(CheckpointBlob(saved_scope,uuid.uuid4(),
     hashlib.sha256(body).hexdigest(),len(body)),saved_allocation,None,storage.namespace)
    assert (await budget_repo.reserve(saved_intent,budget=technical)).dispatch
    await storage.put(saved_scope,saved_intent.blob,io.BytesIO(body))
    await budget_repo.mark_upload_settled(saved_intent)
    async with engine.begin() as db:
     if late=='expired':
      await db.execute(text('UPDATE profile.ide_repository_runtime '
       'SET expires_at=floor(extract(epoch FROM clock_timestamp()))::bigint-1 '
       'WHERE repository_id=:repository_id'),saved_scope.params())
     else:
      await db.execute(text('UPDATE profile.ide_repository_head SET checkpoint_id=:head '
       'WHERE repository_id=:repository_id'),{**saved_scope.params(),'head':older})
    version=await checkpoints.reconcile(saved_scope,saved_intent.blob.checkpoint_id)
    assert version.state=='published' and not version.is_current
    assert version.current_checkpoint_id==(None if late=='expired' else older)
    async with checkpoints.open_saved(saved_scope,saved_intent.blob.checkpoint_id) as (_,source):
     assert source.read()==body
    assert (await runtimes.get_owned(saved_scope)).allocation_id==saved_allocation
    if late=='expired':
     assert (await claim(saved_scope,saved_allocation,saved_intent.blob.checkpoint_id)).dispatch
    else:
     assert (await claim(saved_scope,saved_allocation,
      saved_intent.blob.checkpoint_id)).failure=='runtime_not_expired'
  count+=1
  stage='maintenance_never_expires_unknown_writers_or_restore_pins'
  with tempfile.TemporaryDirectory(prefix='ide-sweep-') as folder:
   storage=IdeCheckpointStorage(LocalFileStorage(folder),max_bytes=100)
   cleanup=IdeCheckpointRetentionService(history,storage)
   body=b'sweep-data'
   async def sweep_fixture(*,settled=True,pin=False,head=False):
    chosen,allocation,checkpoint=await new_repo(published=pin or head)
    blob=CheckpointBlob(chosen,checkpoint,hashlib.sha256(body).hexdigest(),len(body))
    await storage.put(chosen,blob,io.BytesIO(body))
    if pin: assert (await claim(chosen,allocation,checkpoint)).dispatch
    async with engine.begin() as db:
     await db.execute(text('UPDATE profile.ide_checkpoint_intent SET storage_namespace=:namespace,'
      'sha256=:sha,size=:size,state=:state,'
      'published_at=CASE WHEN :head THEN published_at ELSE NULL END,'
      'upload_settled_at=CASE WHEN :settled THEN clock_timestamp() ELSE NULL END '
      'WHERE repository_id=:repository_id AND checkpoint_id=:checkpoint_id'),
      {**chosen.params(),'checkpoint_id':checkpoint,'namespace':storage.namespace,
       'sha':blob.sha256,'size':blob.size,'state':'published' if head else 'retired',
       'head':head,'settled':settled})
     if head: await db.execute(text('INSERT INTO profile.ide_repository_head VALUES '
      '(:repository_id,:checkpoint_id)'),{**chosen.params(),'checkpoint_id':checkpoint})
    return chosen,blob
   target,target_blob=await sweep_fixture()
   unknown,unknown_blob=await sweep_fixture(settled=False)
   pinned,pinned_blob=await sweep_fixture(pin=True)
   current,current_blob=await sweep_fixture(head=True)
   candidates=await history.maintenance_scopes(storage_namespace=storage.namespace)
   assert candidates==[(target,None)]
   before=await budget_repo.accounted_bytes(owner)
   outcome=await cleanup.sweep()
   assert outcome.repositories==1 and outcome.delete_acknowledged==1 and outcome.pending==0
   assert not storage.storage._path(target_blob.key_for(target)).exists()
   assert await budget_repo.accounted_bytes(owner)==before-len(body)
   for chosen,blob in ((unknown,unknown_blob),(pinned,pinned_blob),(current,current_blob)):
    assert storage.storage._path(blob.key_for(chosen)).read_bytes()==body
    assert not (await budget_repo.get_owned(chosen,blob.checkpoint_id)).collected
   assert (await cleanup.sweep()).repositories==0
   count+=1
   stage='maintenance_cursor_batches_and_wrap'
   first,first_blob=await sweep_fixture()
   second,second_blob=await sweep_fixture()
   expected=sorted([first.repository_id,second.repository_id])
   left=await cleanup.sweep(limit=1)
   right=await cleanup.sweep(limit=1,after_repository_id=left.cursor)
   assert [left.cursor,right.cursor]==expected
   assert left.delete_acknowledged==right.delete_acknowledged==1
   assert (await cleanup.sweep(after_repository_id=right.cursor)).cursor is None
   assert not storage.storage._path(first_blob.key_for(first)).exists()
   assert not storage.storage._path(second_blob.key_for(second)).exists()
   assert await history.pending_cleanup(replace(unknown,user_id=other),
    storage_namespace=storage.namespace)==[]
   count+=1
  stage='owner_deletion'
  async with engine.begin() as db:
   await db.execute(text('DELETE FROM profile.ide_repository WHERE repository_id=:repository_id'),
    scope.params())
  assert await records.get_owned(scope,restore_id) is None
  assert await records.publish(scope,restore_id,verified=True) is None
  assert (await claim(scope,allocation,checkpoint)).failure=='missing'
  async with engine.connect() as db:
   assert await db.scalar(text('SELECT count(*) FROM profile.ide_restore_intent '
    'WHERE repository_id=:repository_id'),scope.params())==1
  count+=1
  stage='orphan_thread_deletion_and_late_settlement'
  with tempfile.TemporaryDirectory(prefix='ide-orphan-') as folder:
   storage=IdeCheckpointStorage(LocalFileStorage(folder),max_bytes=100)
   orphan_repo=IdeCheckpointOrphanRepository(connector)
   orphan_cleanup=IdeCheckpointOrphanService(orphan_repo,storage)
   body=b'orphan-data'
   async def orphan_fixture(*,settled=True,pin=False):
    chosen,allocation,checkpoint=await new_repo()
    blob=CheckpointBlob(chosen,checkpoint,hashlib.sha256(body).hexdigest(),len(body))
    intent=CheckpointIntent(blob,allocation,None,storage.namespace)
    await storage.put(chosen,blob,io.BytesIO(body))
    async with engine.begin() as db:
     await db.execute(text('UPDATE profile.ide_checkpoint_intent SET storage_namespace=:namespace,'
      'sha256=:sha,size=:size,upload_settled_at=CASE WHEN :settled '
      'THEN clock_timestamp() ELSE NULL END WHERE repository_id=:repository_id '
      'AND checkpoint_id=:checkpoint_id'),
      {**intent.params(),'namespace':storage.namespace,'sha':blob.sha256,'settled':settled})
     await db.execute(text('INSERT INTO profile.ide_repository_head VALUES '
      '(:repository_id,:checkpoint_id)'),intent.params())
    if pin: assert (await claim(chosen,allocation,checkpoint)).dispatch
    return chosen,intent
   target,target_intent=await orphan_fixture()
   second,second_intent=await orphan_fixture()
   unknown,unknown_intent=await orphan_fixture(settled=False)
   late,late_intent=await orphan_fixture(settled=False)
   pinned,pinned_intent=await orphan_fixture(pin=True)
   pinned_unknown,pinned_unknown_intent=await orphan_fixture(settled=False,pin=True)
   async with engine.connect() as db:
    allocation_before=dict((await db.execute(text('SELECT * FROM profile.ide_restore_intent '
     'WHERE repository_id=:repository_id'),pinned.params())).mappings().one())
   assert (await orphan_cleanup.sweep()).examined==0
   # An existing descriptor of another owner is not an orphan either.
   async with engine.begin() as db:
    await db.execute(text('UPDATE profile.ide_repository SET user_id=:other '
     'WHERE repository_id=:repository_id'),{**target.params(),'other':other})
   assert (await orphan_cleanup.sweep()).examined==0
   async with engine.begin() as db:
    await db.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:thread_id'),
     {'thread_id':thread})
   assert await budget_repo.get_owned(target,target_intent.blob.checkpoint_id) is None
   before=await budget_repo.accounted_bytes(owner)
   # A malicious/incorrect receipt cannot settle the orphan; the exact trusted
   # uploader may record completion, but still cannot publish after deletion.
   wrong_receipt=replace(late_intent,allocation_id=uuid.uuid4())
   assert await budget_repo.mark_upload_settled(wrong_receipt) is None
   receipt=await budget_repo.mark_upload_settled(late_intent)
   assert receipt.upload_settled and not receipt.is_current
   assert await budget_repo.publish(late,late_intent.blob.checkpoint_id,verified=True) is None
   assert await budget_repo.revoke_pending(late,late_intent.blob.checkpoint_id)==(None,False)
   count+=1
   stage='orphan_unknown_revocation_commit_never_deletes'
   ack['next']='after'
   try: await orphan_cleanup.sweep(limit=1)
   except RepositoryError: pass
   else: raise AssertionError('lost orphan retirement acknowledgement accepted')
   for chosen,intent in ((target,target_intent),(second,second_intent),(late,late_intent),
    (pinned,pinned_intent)):
    assert storage.storage._path(intent.blob.key_for(chosen)).read_bytes()==body
   assert await budget_repo.accounted_bytes(owner)==before
   count+=1
   stage='orphan_delete_ack_replay_and_paging'
   retired=await orphan_repo.retire_batch(storage_namespace=storage.namespace,limit=1)
   chosen=retired[0].intent
   assert not await orphan_repo.acknowledge_discard(replace(chosen,storage_namespace='f'*64))
   await storage.discard(chosen.blob.scope,chosen.blob)
   ack['next']='before'
   try: await orphan_repo.acknowledge_discard(chosen)
   except RepositoryError: pass
   else: raise AssertionError('lost collected acknowledgement accepted')
   assert await budget_repo.accounted_bytes(owner)==before
   seen=[]; cursor=None; deleted=0
   for _ in range(5):
    outcome=await orphan_cleanup.sweep(limit=1,after=cursor)
    if not outcome.cursor: break
    seen.append(outcome.cursor); cursor=outcome.cursor
    deleted+=outcome.delete_acknowledged
   assert seen==sorted((i.blob.scope.repository_id,i.blob.checkpoint_id)
    for i in (target_intent,second_intent,late_intent,pinned_intent))
   assert deleted==4
   assert await budget_repo.accounted_bytes(owner)==before-4*len(body)
   for chosen,intent in ((unknown,unknown_intent),(pinned_unknown,pinned_unknown_intent)):
    assert storage.storage._path(intent.blob.key_for(chosen)).read_bytes()==body
   assert (await orphan_cleanup.sweep()).examined==0
   async with engine.connect() as db:
    allocation_after=dict((await db.execute(text('SELECT * FROM profile.ide_restore_intent '
     'WHERE repository_id=:repository_id'),pinned.params())).mappings().one())
   assert allocation_after.pop('state')=='conflict'
   assert allocation_after.pop('active_checkpoint_id') is None
   for name in ('state','active_checkpoint_id','updated_at'): allocation_before.pop(name)
   allocation_after.pop('updated_at')
   assert allocation_after==allocation_before
   assert await records.publish(pinned,allocation_after['restore_id'],verified=True) is None
   assert (await budget_repo.mark_upload_settled(pinned_unknown_intent)).upload_settled
   assert (await orphan_cleanup.sweep()).delete_acknowledged==1
   assert await budget_repo.accounted_bytes(owner)==before-5*len(body)
   count+=1
   stage='orphan_revocation_during_inflight_restore_reader'
   thread=uuid.uuid4()
   async with engine.begin() as db:
    await db.execute(text('INSERT INTO profile.chat_threads VALUES (:id,:owner)'),
     {'id':thread,'owner':owner})
   reading,reading_intent=await orphan_fixture()
   started=asyncio.Event(); release=asyncio.Event(); received=[]
   async def delayed_restore(chosen,attempt,blob,**kwargs):
    source=kwargs['source']
    assert source.read()==body
    received.append(attempt.allocation_id); started.set()
    await release.wait()
    source.seek(0); assert source.read()==body
    return RuntimeObservation('ready',WorkspaceBinding('fixture','PRIVATE',attempt.expires_at))
   async def allocation_ttl(): return 300
   coordinator=IdeRestoreService(records,IdeCheckpointService(budget_repo,storage),
    SimpleNamespace(restore=delayed_restore,allocation_ttl=allocation_ttl),
    limits=CapturePolicy(10,100,100,1000,100,4))
   reading_id=uuid.uuid4()
   inflight=asyncio.create_task(coordinator.restore(reading,reading_id,
    reading_intent.blob.checkpoint_id,reading_intent.allocation_id))
   waiting=asyncio.create_task(started.wait())
   try:
    done,_=await asyncio.wait((waiting,inflight),timeout=3,return_when=asyncio.FIRST_COMPLETED)
    if inflight in done: await inflight
    assert waiting in done
    # A live descriptor is protected, even while its immutable bytes have been
    # fully downloaded into the backend's independent staging stream.
    assert (await orphan_cleanup.sweep()).restore_publications_revoked==0
    async with engine.begin() as db:
     await db.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:thread_id'),
      reading.params())
    outcome=await orphan_cleanup.sweep()
    assert outcome.restore_publications_revoked==1 and outcome.delete_acknowledged==1
    assert not storage.storage._path(reading_intent.blob.key_for(reading)).exists()
   finally:
    release.set()
    waiting.cancel()
   try: await asyncio.wait_for(inflight,3)
   except IdeRepositoryNotFound: pass
   else: raise AssertionError('late restore published a deleted repository')
   assert len(received)==1
   async with engine.connect() as db:
    orphan_allocation=(await db.execute(text('SELECT * FROM profile.ide_restore_intent '
     'WHERE repository_id=:repository_id AND restore_id=:restore_id'),
     {**reading.params(),'restore_id':reading_id})).mappings().one()
    assert orphan_allocation['state']=='conflict'
    assert orphan_allocation['active_checkpoint_id'] is None
    assert orphan_allocation['allocation_id']==received[0]
    assert await db.scalar(text('SELECT count(*) FROM profile.ide_repository_runtime '
     'WHERE repository_id=:repository_id'),reading.params())==0
   count+=1
  stage='migration_roundtrip'
  async with engine.begin() as db:
   await db.run_sync(lambda connection:migrate(connection,True))
   assert await db.scalar(text("SELECT to_regclass('profile.ide_restore_intent')")) is None
   await db.run_sync(migrate)
   assert await db.scalar(text('SELECT count(*) FROM profile.ide_restore_intent'))==0
   await db.run_sync(lambda connection:migrate(connection,True))
  count+=1
 finally:
  if engine is not None: await engine.dispose()
  if created:
   await admin.execute('DROP DATABASE "'+database+'"')
   assert not await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',database)
  await admin.close()
 print(json.dumps({'cases':count,'fixture_removed':True,'source_parity':True,'runtime_allocations':0}))

try: asyncio.run(main())
except BaseException as error:
 print(json.dumps({'status':'failed','stage':stage,'error':type(error).__name__}))
 raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_IDE_RESTORE_JOURNAL") != "1",
    reason="explicit isolated PostgreSQL restore journal acceptance",
)
def test_real_postgres_restore_claim_replay_swap_and_commit_loss():
    root = Path(__file__).resolve().parents[1]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in FILES}
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            "import json,sys; probe_input=json.load(sys.stdin); exec(probe_input['probe'])",
        ],
        input=json.dumps({"files": files, "probe": PROBE}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        pytest.fail("restore_journal_probe_output_invalid")
    assert result.returncode == 0, f"restore_journal_probe_failed:{outcome}"
    assert outcome == {
        "cases": 23,
        "fixture_removed": True,
        "source_parity": True,
        "runtime_allocations": 0,
    }
