"""Opt-in real SQL/temporary local-object publication; no working DB migration."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

FILES = (
    "alembic/versions/032_ide_repositories.py",
    "alembic/versions/033_ide_runtime_claims.py",
    "alembic/versions/034_ide_checkpoint_revisions.py",
    "service/services/chat/domain/ide/checkpoints/blob.py",
    "service/services/chat/domain/ide/checkpoints/revision.py",
    "service/services/chat/domain/ide/runtime.py",
    "service/services/chat/persistence/ide/checkpoints/repository.py",
    "service/services/chat/application/ide/checkpoints/service.py",
    "service/infrastructure/ide/checkpoint_storage.py",
    "service/infrastructure/storage/bounded_download.py",
    "service/infrastructure/storage/local_file_storage.py",
    "service/infrastructure/storage/identity.py",
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
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.repositories import IdeRepositoryService
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
logging.disable(logging.CRITICAL)
stage='source_parity'
diagnostic={}

class AckSession(AsyncSession):
 async def execute(self,statement,*args,**kwargs):
  try: return await super().execute(statement,*args,**kwargs)
  except Exception as error:
   diagnostic['db_error']=type(error).__name__
   diagnostic['sqlstate']=getattr(getattr(error,'orig',None),'sqlstate',None)
   raise
 async def commit(self):
  mode=self.info.pop('lose_ack',None)
  if mode=='before': raise OperationalError('PRIVATE_SQL',{},Exception('PRIVATE_DB'))
  await super().commit()
  if mode=='after': raise OperationalError('PRIVATE_SQL',{},Exception('PRIVATE_DB'))

class Transport:
 def __init__(self, actual):
  self.actual=actual; self.max_bytes=actual.max_bytes; self.puts=0; self.namespace=actual.namespace
  self.barrier=None; self.armed=None; self.open=actual.open; self.gate=None
 async def put(self,*args):
  self.puts+=1
  if self.gate is not None:
   self.gate['entered'].set()
   await asyncio.wait_for(self.gate['release'].wait(),5)
  await self.actual.put(*args)
  if self.barrier is not None:
   self.barrier['count']+=1
   if self.barrier['count']==2: self.barrier['ready'].set()
   await asyncio.wait_for(self.barrier['ready'].wait(),5)
  if self.armed is not None:
   self.armed['next']='after'; self.armed=None

async def main():
 global stage
 files=json.load(sys.stdin)['files']
 assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
  for path,digest in files.items())
 for path in files:
  if path.startswith('service/'):
   module=__import__(path[:-3].replace('/','.'),fromlist=['__file__'])
   assert Path(module.__file__).resolve()==Path(path).resolve()
 assert config.pg.host=='postgres'
 database='gpthub_ide_cp_'+uuid.uuid4().hex[:24]
 assert re.fullmatch(r'gpthub_ide_cp_[0-9a-f]{24}',database)
 admin=await asyncpg.connect(host=config.pg.host,port=config.pg.port,user=config.pg.user,
  password=config.pg.password,database=config.pg.db,timeout=5)
 engine=None; created=False; count=0; failure_stage=None
 try:
  stage='fixture_database'
  await admin.execute('CREATE DATABASE "'+database+'"'); created=True
  engine=create_async_engine(URL.create('postgresql+asyncpg',host=config.pg.host,
   port=config.pg.port,username=config.pg.user,password=config.pg.password,database=database),echo=False)
  migrations=[]
  for number in ('032_ide_repositories','033_ide_runtime_claims','034_ide_checkpoint_revisions'):
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
   await db.run_sync(migrate)
  count+=1
  factory=async_sessionmaker(engine,class_=AckSession,expire_on_commit=False)
  ack={'next':None}
  @asynccontextmanager
  async def session_context():
   async with factory() as db:
    db.info['lose_ack']=ack['next']; ack['next']=None
    yield db
  connector=SimpleNamespace(get_session_context=session_context)
  repos=IdeRepositoryService(IdeRepositoryRepository(connector))
  records=IdeCheckpointRepository(connector)
  owner,other,thread,sibling=[uuid.uuid4() for _ in range(4)]
  async with engine.begin() as db:
   for uid in (owner,other):
    await db.execute(text('INSERT INTO profile."user" VALUES (:id)'),{'id':uid})
   for tid in (thread,sibling):
    await db.execute(text('INSERT INTO profile.chat_threads VALUES (:id,:owner)'),
     {'id':tid,'owner':owner})
  async def new_repo(tid=thread):
   row=await repos.register(thread_id=tid,user_id=owner,
    creation_intent_id=uuid.uuid4(),name='Fixture')
   scope=RepositoryScope(tid,owner,uuid.UUID(row['repository_id'])); allocation=uuid.uuid4()
   async with engine.begin() as db:
    await db.execute(text("INSERT INTO profile.ide_repository_runtime "
     "(repository_id,allocation_id,expires_at,state) VALUES (:repo,:allocation,"
     "floor(extract(epoch FROM clock_timestamp()))::bigint+600,'ready')"),
     {'repo':scope.repository_id,'allocation':allocation})
   return scope,allocation
  scope,allocation=await new_repo()
  def intent(body=b'fixture\0\xff',base=None,chosen=scope,generation=allocation):
   blob=CheckpointBlob(chosen,uuid.uuid4(),hashlib.sha256(body).hexdigest(),len(body))
   return CheckpointIntent(blob,generation,base,transport.namespace)
  with tempfile.TemporaryDirectory(prefix='ide-revisions-') as folder:
   native=LocalFileStorage(folder)
   transport=Transport(IdeCheckpointStorage(native,max_bytes=10000))
   service=IdeCheckpointService(records,transport)
   stage='owned_reservation'
   for changes in ({'user_id':other},{'thread_id':sibling},{'repository_id':uuid.uuid4()}):
    foreign=replace(scope,**changes)
    assert (await records.reserve(intent(chosen=foreign))).failure=='missing'
   count+=1
   assert (await records.reserve(intent(generation=uuid.uuid4()))).failure=='runtime_not_ready'
   count+=1
   stage='parallel_single_intent'
   first=intent()
   reservations=await asyncio.gather(*(records.reserve(first) for _ in range(8)))
   assert sum(value.dispatch for value in reservations)==1
   assert all(value.record.intent==first for value in reservations)
   count+=1
   stage='recover_uploaded_unpublished'
   await transport.actual.put(scope,first.blob,io.BytesIO(b'fixture\0\xff'))
   published=await service.reconcile(scope,first.blob.checkpoint_id)
   assert published.is_current and (await records.head(scope))==published
   count+=1
   stage='owned_published_reads'
   for changes in ({'user_id':other},{'thread_id':sibling},{'repository_id':uuid.uuid4()}):
    foreign=replace(scope,**changes)
    assert await records.get_owned(foreign,first.blob.checkpoint_id) is None
    assert await records.head(foreign) is None
   count+=1
   class ForbiddenStream:
    def seek(self,*_): raise AssertionError('replay_sought_source')
    def read(self,*_): raise AssertionError('replay_read_source')
   puts=transport.puts
   assert await service.save(scope,first,ForbiddenStream())==published
   assert transport.puts==puts
   count+=1
   stage='intent_mismatch'
   for changed in (replace(first,allocation_id=uuid.uuid4()),
    replace(first,base_checkpoint_id=uuid.uuid4()),
    replace(first,blob=replace(first.blob,sha256='a'*64)),replace(first,blob=replace(first.blob,size=1))):
    try: await service.save(scope,changed,ForbiddenStream())
    except IdeCheckpointError as error: assert error.code=='ide_checkpoint_intent_mismatch'
    else: raise AssertionError('payload_changed')
   assert transport.puts==puts
   count+=1
   stage='parallel_distinct_intents'
   a,b=intent(b'version A',first.blob.checkpoint_id),intent(b'version B',first.blob.checkpoint_id)
   transport.barrier={'count':0,'ready':asyncio.Event()}
   outcomes=await asyncio.gather(service.save(scope,a,io.BytesIO(b'version A')),
    service.save(scope,b,io.BytesIO(b'version B')))
   transport.barrier=None
   assert sorted(row.state for row in outcomes)==['conflict','published']
   winner=next(row for row in outcomes if row.is_current)
   assert (await records.head(scope)).intent==winner.intent
   count+=1
   stage='same_intent_during_inflight_upload'
   double_scope,double_generation=await new_repo()
   double=intent(b'one upload',chosen=double_scope,generation=double_generation)
   transport.gate={'entered':asyncio.Event(),'release':asyncio.Event()}
   puts=transport.puts
   first_task=asyncio.create_task(service.save(double_scope,double,io.BytesIO(b'one upload')))
   try:
    await asyncio.wait_for(transport.gate['entered'].wait(),5)
    try: await service.save(double_scope,double,ForbiddenStream())
    except IdeCheckpointError as error: assert error.code=='ide_checkpoint_storage_unavailable'
    else: raise AssertionError('unobserved_upload_acknowledged')
    assert transport.puts==puts+1
   finally:
    transport.gate['release'].set()
    double_saved=await first_task
    transport.gate=None
   assert double_saved.is_current
   count+=1
   stage='historical_replay'
   old=await service.save(scope,first,ForbiddenStream())
   assert old.state=='published' and not old.is_current
   assert (await records.head(scope)).intent==winner.intent
   count+=1
   stage='stale_base_before_upload'
   stale=intent(b'old source',first.blob.checkpoint_id); puts=transport.puts
   assert (await service.save(scope,stale,ForbiddenStream())).state=='conflict'
   assert transport.puts==puts and not native._path(stale.blob.key_for(scope)).exists()
   count+=1
   stage='missing_object_never_publishes'
   missing=intent(b'missing source',winner.intent.blob.checkpoint_id)
   assert (await records.reserve(missing)).dispatch
   try: await service.reconcile(scope,missing.blob.checkpoint_id)
   except IdeCheckpointError as error: assert error.code=='ide_checkpoint_storage_unavailable'
   else: raise AssertionError('missing_published')
   assert (await records.head(scope)).intent==winner.intent
   count+=1
   stage='lost_reserve_ack'
   uncertain=intent(b'uncertain',winner.intent.blob.checkpoint_id); puts=transport.puts
   ack['next']='after'
   row=await service.save(scope,uncertain,ForbiddenStream())
   assert row.state=='pending' and transport.puts==puts
   assert (await records.get_owned(scope,uncertain.blob.checkpoint_id)).state=='pending'
   count+=1
   stage='claim_rollback_no_dispatch'
   rolled_back=intent(b'rolled back',winner.intent.blob.checkpoint_id); ack['next']='before'
   try: await service.save(scope,rolled_back,ForbiddenStream())
   except IdeCheckpointError as error: assert error.code=='ide_checkpoint_status_unknown'
   else: raise AssertionError('uncertain_claim_dispatched')
   assert await records.get_owned(scope,rolled_back.blob.checkpoint_id) is None
   assert transport.puts==puts
   count+=1
   stage='lost_publish_ack'
   final=intent(b'final version',winner.intent.blob.checkpoint_id); transport.armed=ack
   saved=await service.save(scope,final,io.BytesIO(b'final version'))
   assert saved.is_current and (await records.head(scope)).intent==final
   count+=1
   stage='superseded_unuploaded_intent'
   assert (await service.reconcile(scope,missing.blob.checkpoint_id)).state=='conflict'
   count+=1
   stage='fresh_session_owner'
   fresh=IdeCheckpointRepository(SimpleNamespace(get_session_context=factory))
   assert (await fresh.head(scope)).intent==final
   count+=1
   stage='published_bytes_after_runtime_expiry'
   async with engine.begin() as db:
    await db.execute(text('UPDATE profile.ide_repository_runtime SET expires_at=1 '
     'WHERE repository_id=:repo'),{'repo':scope.repository_id})
   recovered=IdeCheckpointService(fresh,transport.actual)
   async with recovered.open_saved(scope,final.blob.checkpoint_id) as (revision,source):
    assert revision.is_current and source.read()==b'final version'
   assert source.closed
   count+=1
   stage='storage_namespace_fence'
   wrong=IdeCheckpointStorage(LocalFileStorage(Path(folder)/'other-store'),max_bytes=10000)
   await wrong.put(scope,final.blob,io.BytesIO(b'final version'))
   try:
    async with IdeCheckpointService(fresh,wrong).open_saved(scope,final.blob.checkpoint_id):
     raise AssertionError('wrong_namespace_opened')
   except IdeCheckpointError as error: assert error.code=='ide_checkpoint_storage_changed'
   count+=1
   stage='generation_retirement'
   for scenario in ('generation','expiry','unknown'):
    other_scope,generation=await new_repo()
    body=b'captured state'; capture=intent(body,chosen=other_scope,generation=generation)
    assert (await records.reserve(capture)).dispatch
    await transport.actual.put(other_scope,capture.blob,io.BytesIO(body))
    async with engine.begin() as db:
     assignment={'generation':'allocation_id=:new','expiry':'expires_at=1','unknown':"state='unknown'"}[scenario]
     await db.execute(text('UPDATE profile.ide_repository_runtime SET '+assignment+
      ' WHERE repository_id=:repo'),
      {'repo':other_scope.repository_id,'new':uuid.uuid4()})
    observed=await service.reconcile(other_scope,capture.blob.checkpoint_id)
    assert observed.state==('pending' if scenario=='unknown' else 'retired')
    assert await records.head(other_scope) is None
    if scenario=='unknown':
     async with engine.begin() as db:
      await db.execute(text("UPDATE profile.ide_repository_runtime SET state='ready' "
       'WHERE repository_id=:repo'),
       {'repo':other_scope.repository_id})
     assert (await service.reconcile(other_scope,capture.blob.checkpoint_id)).is_current
    count+=1
   stage='thread_delete_preserves_private_object_ledger'
   deleted_thread=uuid.uuid4()
   async with engine.begin() as db:
    await db.execute(text('INSERT INTO profile.chat_threads VALUES (:thread,:owner)'),
     {'thread':deleted_thread,'owner':owner})
   deleted_scope,deleted_generation=await new_repo(deleted_thread)
   abandoned=intent(b'abandoned',chosen=deleted_scope,generation=deleted_generation)
   assert (await records.reserve(abandoned)).dispatch
   await transport.actual.put(deleted_scope,abandoned.blob,io.BytesIO(b'abandoned'))
   async with engine.begin() as db:
    await db.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:thread'),
     {'thread':deleted_thread})
    assert await db.scalar(text('SELECT count(*) FROM profile.ide_checkpoint_intent '
     'WHERE repository_id=:repo'),{'repo':deleted_scope.repository_id})==1
    assert await db.scalar(text('SELECT count(*) FROM profile.ide_repository_head '
     'WHERE repository_id=:repo'),{'repo':deleted_scope.repository_id})==0
   assert await records.get_owned(deleted_scope,abandoned.blob.checkpoint_id) is None
   assert await records.publish(deleted_scope,abandoned.blob.checkpoint_id) is None
   assert (await records.reserve(abandoned)).failure=='missing'
   count+=1
   stage='database_constraints'
   for fields in ({'size':-1},{'sha256':'bad'},{'storage_namespace':'bad'},
    {'state':'unknown'},{'state':'published'},
    {'base_checkpoint_id':final.blob.checkpoint_id,'checkpoint_id':final.blob.checkpoint_id}):
    values={**intent().params(),'state':'pending',**fields}
    try:
     async with engine.begin() as db:
      await db.execute(text('INSERT INTO profile.ide_checkpoint_intent '
       '(repository_id,checkpoint_id,thread_id,user_id,allocation_id,'
       'base_checkpoint_id,sha256,size,storage_namespace,state) '
       'VALUES (:repository_id,:checkpoint_id,:thread_id,:user_id,:allocation_id,'
       ':base_checkpoint_id,:sha256,:size,:storage_namespace,:state)'),values)
    except IntegrityError: pass
    else: raise AssertionError('database_constraint_missing')
   try:
    async with engine.begin() as db:
     await db.execute(text('UPDATE profile.ide_repository_head SET checkpoint_id=:foreign '
      'WHERE repository_id=:repo'),
      {'foreign':double.blob.checkpoint_id,'repo':scope.repository_id})
   except IntegrityError: pass
   else: raise AssertionError('cross_repo_head_fk_missing')
   count+=1
  stage='migration_downgrade'
  async with engine.begin() as db:
   await db.run_sync(lambda connection:migrate(connection,True))
   tables=('ide_repository','ide_repository_runtime','ide_repository_head','ide_checkpoint_intent')
   for table in tables:
    assert await db.scalar(text('SELECT to_regclass(:table)'),{'table':'profile.'+table}) is None
  count+=1
 except BaseException:
  failure_stage=stage
  raise
 finally:
  if engine is not None: await engine.dispose()
  if created:
   await admin.execute('DROP DATABASE "'+database+'"')
   assert not await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',database)
  await admin.close()
  if failure_stage is not None: stage=failure_stage
 print(json.dumps({'cases':count,'fixture_removed':True,'source_parity':True,'runtime_allocations':0}))

try: asyncio.run(main())
except BaseException as error:
 print(json.dumps({'status':'failed','stage':stage,'error':type(error).__name__,**diagnostic}))
 raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_IDE_CHECKPOINT_REVISIONS") != "1",
    reason="explicit disposable PostgreSQL checkpoint acceptance",
)
def test_real_postgres_checkpoint_ownership_cas_uncertain_commit_and_deletion():
    root = Path(__file__).resolve().parents[1]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in FILES}
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", PROBE],
        input=json.dumps({"files": files}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        pytest.fail("checkpoint_postgres_probe_output_invalid")
    assert result.returncode == 0, f"checkpoint_postgres_probe_failed:{outcome}"
    assert outcome == {
        "cases": 26,
        "fixture_removed": True,
        "source_parity": True,
        "runtime_allocations": 0,
    }
