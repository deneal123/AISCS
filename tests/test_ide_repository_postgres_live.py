"""Opt-in descriptor concurrency proof in a fresh, disposable PostgreSQL database.

No deployment migration, user rows, runtime sandboxes or model calls are touched.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILES = (
    "service/services/chat/persistence/ide/repositories.py",
    "service/services/chat/application/ide/repositories.py",
    "alembic/versions/032_ide_repositories.py",
    "alembic/versions/033_ide_runtime_claims.py",
    "alembic/versions/035_ide_onboarding_identity.py",
    "alembic/versions/036_ide_clone_intents.py",
    "alembic/versions/037_ide_clone_recovery.py",
    "service/services/chat/persistence/ide/clones.py",
    "service/services/chat/domain/ide/runtime.py",
    "service/services/chat/persistence/ide/runtime.py",
    "service/services/chat/application/ide/runtime.py",
)

_PROBE = r"""
import asyncio, hashlib, importlib.util, json, logging, re, sys, uuid
from pathlib import Path
from types import SimpleNamespace
logging.disable(logging.CRITICAL)
import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from service.settings import config
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.services.chat.application.ide.repositories import (
    IdeRepositoryService, IdeRepositoryNotFound, IdeRepositoryIntentConflict
)
from service.services.chat.domain.ide.runtime import RepositoryScope, RuntimeObservation
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.persistence.ide.clones import IdeCloneRepository

stage = 'source_parity'
async def main():
    global stage
    files = json.load(sys.stdin)['files']
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in files.items())
    assert config.pg.host == 'postgres'
    database = 'gpthub_ide_test_' + uuid.uuid4().hex[:24]
    assert re.fullmatch(r'gpthub_ide_test_[0-9a-f]{24}', database)
    stage = 'fixture_allocation'
    admin = await asyncpg.connect(host=config.pg.host, port=config.pg.port,
        user=config.pg.user, password=config.pg.password, database=config.pg.db, timeout=5)
    created = False
    engine = None
    cases = 0
    runtime_cases = 0
    onboarding_cases = 0
    clone_cases = 0
    recovery_cases = 0
    try:
        await admin.execute('CREATE DATABASE "' + database + '"')
        created = True
        engine = create_async_engine(URL.create('postgresql+asyncpg', host=config.pg.host,
            port=config.pg.port, username=config.pg.user, password=config.pg.password,
            database=database), echo=False)
        stage = 'migration_upgrade'
        spec = importlib.util.spec_from_file_location('ide_migration',
            'alembic/versions/032_ide_repositories.py')
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        runtime_spec = importlib.util.spec_from_file_location('runtime_migration',
            'alembic/versions/033_ide_runtime_claims.py')
        runtime_migration = importlib.util.module_from_spec(runtime_spec)
        runtime_spec.loader.exec_module(runtime_migration)
        starter_spec = importlib.util.spec_from_file_location('starter_migration',
            'alembic/versions/035_ide_onboarding_identity.py')
        starter_migration = importlib.util.module_from_spec(starter_spec)
        starter_spec.loader.exec_module(starter_migration)
        clone_spec = importlib.util.spec_from_file_location('clone_migration',
            'alembic/versions/036_ide_clone_intents.py')
        clone_migration = importlib.util.module_from_spec(clone_spec)
        clone_spec.loader.exec_module(clone_migration)
        recovery_spec = importlib.util.spec_from_file_location('recovery_migration',
            'alembic/versions/037_ide_clone_recovery.py')
        recovery_migration = importlib.util.module_from_spec(recovery_spec)
        recovery_spec.loader.exec_module(recovery_migration)
        def upgrade(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                runtime_migration.upgrade()
                starter_migration.upgrade()
                clone_migration.upgrade()
                recovery_migration.upgrade()
        async with engine.begin() as connection:
            await connection.execute(text('CREATE SCHEMA profile'))
            await connection.execute(text('CREATE TABLE profile."user" (id uuid PRIMARY KEY)'))
            await connection.execute(text('CREATE TABLE profile.chat_threads '
                '(thread_id uuid UNIQUE NOT NULL, user_id uuid, title text, '
                'created_at timestamptz, updated_at timestamptz)'))
            await connection.run_sync(upgrade)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repository = IdeRepositoryRepository(SimpleNamespace(get_session_context=factory))
        service = IdeRepositoryService(repository)
        owner, other, thread, sibling, foreign = [uuid.uuid4() for _ in range(5)]
        async with engine.begin() as connection:
            for uid in (owner, other):
                await connection.execute(text('INSERT INTO profile."user" VALUES (:id)'),
                    {'id':uid})
            for tid, uid in ((thread, owner), (sibling, owner), (foreign, other)):
                await connection.execute(text('INSERT INTO profile.chat_threads '
                    '(thread_id,user_id) VALUES (:id,:uid)'),
                    {'id':tid, 'uid':uid})
        scope = {'thread_id':thread, 'user_id':owner}
        stage = 'parallel_registration'
        args = {**scope, 'creation_intent_id':uuid.uuid4(), 'name':'Repository A'}
        results = await asyncio.gather(*(service.register(**args) for _ in range(8)))
        assert len({row['repository_id'] for row in results}) == 1
        assert all(row['state'] == 'registered' for row in results)
        cases += 1
        retry = await service.register(**args)
        assert retry == results[0]
        cases += 1
        try:
            await service.register(**{**args, 'name':'Different'})
        except IdeRepositoryIntentConflict:
            cases += 1
        else:
            raise AssertionError('intent_payload_changed')
        second = await service.register(**{**args, 'creation_intent_id':uuid.uuid4(),
            'name':'Repository B'})
        assert second['repository_id'] != retry['repository_id']
        cases += 1
        stage = 'ownership_and_pagination'
        repository_id = uuid.UUID(retry['repository_id'])
        for tid, uid in ((thread,other),(sibling,owner),(foreign,other)):
            try:
                await service.get(thread_id=tid,user_id=uid,repository_id=repository_id)
            except IdeRepositoryNotFound:
                cases += 1
            else:
                raise AssertionError('cross_scope_read')
        for tid, uid in ((thread,other),(uuid.uuid4(),owner)):
            try:
                await service.register(**{**args,'thread_id':tid,'user_id':uid})
            except IdeRepositoryNotFound:
                cases += 1
            else:
                raise AssertionError('cross_scope_create')
        first = await service.list(**scope, limit=1, offset=0)
        last = await service.list(**scope, limit=1, offset=first['next_offset'])
        assert first['next_offset'] == 1 and last['next_offset'] is None
        assert len({first['items'][0]['repository_id'],last['items'][0]['repository_id']}) == 2
        cases += 1
        # A different HTTP service/session owner still reads the same durable rows.
        fresh = IdeRepositoryService(IdeRepositoryRepository(
            SimpleNamespace(get_session_context=factory)))
        assert len((await fresh.list(**scope,limit=30,offset=0))['items']) == 2
        cases += 1
        # Draft navigation never writes. Explicit concurrent setup atomically
        # creates just one owned thread/descriptor, and cannot claim a foreign one.
        draft = uuid.uuid4()
        assert await fresh.list(thread_id=draft,user_id=owner,limit=30,offset=0) == {
            'items':[], 'next_offset':None}
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM profile.chat_threads '
                'WHERE thread_id=:id'), {'id':draft}) == 0
        setup = {**args,'thread_id':draft,'creation_intent_id':uuid.uuid4(),
            'create_thread_if_missing':True}
        drafts = await asyncio.gather(*(fresh.register(**setup) for _ in range(8)))
        assert len({row['repository_id'] for row in drafts}) == 1
        try:
            await fresh.register(**{**setup,'thread_id':foreign})
        except IdeRepositoryNotFound:
            pass
        else:
            raise AssertionError('draft_took_foreign_owner')
        async with engine.begin() as connection:
            await connection.execute(text('DELETE FROM profile.chat_threads WHERE thread_id=:id'),
                {'id':draft})
        cases += 1
        async with engine.connect() as connection:
            count = await connection.scalar(text('SELECT count(*) FROM profile.ide_repository'))
            assert count == 2
        cases += 1
        stage = 'default_identity_concurrency'
        # Existing explicit repositories win. Entry never creates a starter
        # beside known work, nor changes a manual row into a trusted starter.
        existing = await fresh.ensure_default(**scope)
        assert existing['repository_id'] in {retry['repository_id'],second['repository_id']}
        assert await repository.is_onboarding_owned(**scope,repository_id=repository_id) is False
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE onboarding_created')) == 0
        onboarding_cases += 1
        starter_thread, race_thread = uuid.uuid4(), uuid.uuid4()
        starter_scope = {'thread_id':starter_thread,'user_id':owner}
        starters = await asyncio.gather(*(fresh.ensure_default(**starter_scope) for _ in range(8)))
        assert len({row['repository_id'] for row in starters}) == 1
        assert await service.ensure_default(**starter_scope) == starters[0]
        assert await repository.is_onboarding_owned(**starter_scope,
            repository_id=uuid.UUID(starters[0]['repository_id'])) is True
        assert await repository.is_onboarding_owned(thread_id=starter_thread,user_id=other,
            repository_id=uuid.UUID(starters[0]['repository_id'])) is None
        onboarding_cases += 1
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE thread_id=:id AND onboarding_created'), {'id':starter_thread}) == 1
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE thread_id=:id'), {'id':starter_thread}) == 1
        onboarding_cases += 1
        async with engine.begin() as connection:
            await connection.execute(text('UPDATE profile.ide_repository SET name=:name '
                'WHERE thread_id=:id'), {'id':starter_thread,'name':'Renamed starter'})
        renamed = await fresh.ensure_default(**starter_scope)
        assert renamed['repository_id'] == starters[0]['repository_id']
        assert renamed['name'] == 'Renamed starter'
        assert 'onboarding_created' not in renamed
        onboarding_cases += 1
        # The schema is a second guard even if a future writer omits the parent lock.
        try:
            async with engine.begin() as connection:
                await connection.execute(text('INSERT INTO profile.ide_repository '
                    '(repository_id,thread_id,user_id,creation_intent_id,name,onboarding_created) '
                    'VALUES (:repo,:tid,:uid,:intent,:name,TRUE)'),
                    {'repo':uuid.uuid4(),'tid':starter_thread,'uid':owner,
                     'intent':uuid.uuid4(),'name':'Duplicate starter'})
        except IntegrityError:
            pass
        else:
            raise AssertionError('starter_unique_index_missing')
        onboarding_cases += 1
        for tid, uid in ((starter_thread,other),(foreign,owner)):
            try:
                await fresh.ensure_default(thread_id=tid,user_id=uid)
            except IdeRepositoryNotFound:
                pass
            else:
                raise AssertionError('default_took_foreign_owner')
        onboarding_cases += 1
        race_scope = {'thread_id':race_thread,'user_id':owner}
        manual = {**race_scope,'creation_intent_id':uuid.uuid4(),
            'name':'Explicit racing project','create_thread_if_missing':True}
        await asyncio.gather(*(fresh.ensure_default(**race_scope) for _ in range(4)),
            *(fresh.register(**manual) for _ in range(4)))
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE thread_id=:id AND NOT onboarding_created'), {'id':race_thread}) == 1
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE thread_id=:id AND onboarding_created'), {'id':race_thread}) <= 1
        onboarding_cases += 1
        async with engine.begin() as connection:
            await connection.execute(text('UPDATE profile.chat_threads SET title=:title '
                'WHERE thread_id=:id'), {'id':starter_thread,'title':'Keep user title'})
        await fresh.ensure_default(**starter_scope)
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT title FROM profile.chat_threads '
                'WHERE thread_id=:id'), {'id':starter_thread}) == 'Keep user title'
        onboarding_cases += 1
        async with engine.begin() as connection:
            for tid in (starter_thread,race_thread):
                await connection.execute(
                    text('DELETE FROM profile.chat_threads WHERE thread_id=:id'),
                    {'id':tid})
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository')) == 2
        onboarding_cases += 1
        stage = 'runtime_dispatch_and_observation'
        connector = SimpleNamespace(get_session_context=factory)
        runtimes = IdeRuntimeRepository(connector)
        scope_a = RepositoryScope(thread,owner,repository_id)
        scope_b = RepositoryScope(thread,owner,uuid.UUID(second['repository_id']))
        class AllocationClient:
            def __init__(self):
                self.creates = []
                self.created = set()
                self.reads = 0
                self.quota = False
            async def allocation_ttl(self): return 600
            async def observe(self,user_id,attempt,*,create=False):
                assert user_id == owner
                if create:
                    self.creates.append(attempt.allocation_id)
                    if self.quota:
                        self.quota = False
                        return RuntimeObservation('rejected',retry_allowed=True)
                    await asyncio.sleep(0.05)
                    self.created.add(attempt.allocation_id)
                    return RuntimeObservation('ready')
                self.reads += 1
                state = 'ready' if attempt.allocation_id in self.created else 'unknown'
                return RuntimeObservation(state)
        client = AllocationClient()
        runtime_service = IdeRuntimeService(repository,runtimes,client)
        assert (await runtime_service.status(scope_a))['workspace']['state'] == 'not_created'
        assert not client.creates and client.reads == 0
        runtime_cases += 1
        await asyncio.gather(*(runtime_service.provision(scope_a) for _ in range(8)))
        assert len(client.creates) == 1
        current = await runtimes.get_owned(scope_a)
        assert current is not None
        generation,deadline = current.allocation_id,current.expires_at
        runtime_cases += 1
        fresh_runtime = IdeRuntimeService(repository,IdeRuntimeRepository(connector),client)
        assert (await fresh_runtime.provision(scope_a))['workspace']['state'] == 'ready'
        assert len(client.creates) == 1
        assert (await runtimes.get_owned(scope_a)).allocation_id == generation
        runtime_cases += 1
        old = await runtimes.begin_observation(scope_a,current)
        newer = await runtimes.begin_observation(scope_a,current)
        await runtimes.record_observation(scope_a,newer,'unknown')
        actual = await runtimes.record_observation(scope_a,old,'ready')
        assert actual.state == 'unknown' and actual.observation == newer.observation
        runtime_cases += 1
        wrong_scope = RepositoryScope(thread,other,repository_id)
        assert await runtimes.get_owned(wrong_scope) is None
        assert await runtimes.claim(wrong_scope,ttl_sec=600) == (None,False)
        runtime_cases += 1
        async with engine.begin() as connection:
            await connection.execute(text('UPDATE profile.ide_repository_runtime SET expires_at=1 '
                'WHERE repository_id=:id'),{'id':repository_id})
        reads = client.reads
        assert (await runtime_service.provision(scope_a))['workspace']['state'] == 'expired'
        assert len(client.creates) == 1 and client.reads == reads
        assert (await runtimes.get_owned(scope_a)).allocation_id == generation
        runtime_cases += 1
        client.quota = True
        rejected = await runtime_service.provision(scope_b)
        before = await runtimes.get_owned(scope_b)
        assert rejected['workspace']['state'] == 'rejected' and rejected['workspace']['can_retry']
        reads = client.reads
        assert await runtime_service.status(scope_b) == rejected
        assert client.reads == reads
        no_retry, dispatch = await runtimes.claim(scope_b,ttl_sec=600,allow_retry=False)
        assert not dispatch and no_retry.allocation_id == before.allocation_id
        assert no_retry.state == 'rejected' and no_retry.retry_allowed
        assert await runtime_service.provision(scope_b,allow_retry=False) == rejected
        assert client.creates.count(before.allocation_id) == 1
        assert (await runtime_service.provision(scope_b))['workspace']['state'] == 'ready'
        after = await runtimes.get_owned(scope_b)
        assert before.allocation_id == after.allocation_id and before.expires_at == after.expires_at
        assert client.creates.count(before.allocation_id) == 2
        runtime_cases += 1
        # A committed claim with no dispatched request models a process loss.
        third = await service.register(**{**args,'creation_intent_id':uuid.uuid4(),'name':'C'})
        scope_c = RepositoryScope(thread,owner,uuid.UUID(third['repository_id']))
        orphan,dispatch = await runtimes.claim(scope_c,ttl_sec=600)
        assert dispatch and orphan is not None
        creates = len(client.creates)
        recovered = await fresh_runtime.provision(scope_c)
        assert recovered['workspace']['state'] == 'unknown'
        assert not recovered['workspace']['can_retry']
        assert len(client.creates) == creates
        runtime_cases += 1
        async with engine.connect() as connection:
            count = await connection.scalar(
                text('SELECT count(*) FROM profile.ide_repository_runtime'))
            assert count == 3
        runtime_cases += 1
        stage = 'isolated_clone_identity_and_dispatch'
        clones = IdeCloneRepository(connector)
        clone_id = uuid.uuid4()
        clone_args = dict(intent_id=clone_id,request_digest='a'*64,name='cloned-repo')
        denied = await clones.reserve(wrong_scope,**clone_args)
        assert denied is None
        clone_cases += 1
        destinations = await asyncio.gather(*(clones.reserve(scope_a,**clone_args)
            for _ in range(8)))
        destination = destinations[0]['repository_id']
        target_scope = RepositoryScope(thread,owner,destination)
        assert (await clones.latest_owned(scope_a))['repository_id']==destination
        assert (await clones.latest_owned(target_scope))['repository_id']==destination
        assert await clones.latest_owned(wrong_scope) is None
        recovery_cases += 1
        assert all(row['repository_id']==destination for row in destinations)
        assert destination not in {scope_a.repository_id,scope_b.repository_id,
            scope_c.repository_id}
        clone_cases += 1
        identity = dict(thread_id=thread,user_id=owner,intent_id=clone_id)
        fresh_clones = IdeCloneRepository(connector)
        replay = await fresh_clones.reserve(scope_a,**{**clone_args,'request_digest':'b'*64})
        assert replay['request_digest']=='a'*64 and replay['repository_id']==destination
        assert replay['origin'] is None and replay['branch'] is None
        changed = await clones.reserve(scope_a,**{**clone_args,'request_digest':'b'*64,
            'origin':'https://github.com/other/repo.git','branch':'main'})
        assert changed['origin'] is None
        recovered = await clones.reserve(scope_a,**{**clone_args,
            'origin':'https://github.com/fixture/repo.git','branch':'main'})
        assert recovered['origin']=='https://github.com/fixture/repo.git'
        assert recovered['branch']=='main'
        immutable = await clones.reserve(scope_a,**{**clone_args,
            'origin':'https://github.com/other/repo.git','branch':'changed'})
        assert immutable['origin']==recovered['origin'] and immutable['branch']=='main'
        recovery_cases += 1
        clone_cases += 1
        assert await clones.get_owned(**{**identity,'user_id':other}) is None
        assert await clones.get_owned(**{**identity,'thread_id':sibling}) is None
        clone_cases += 1
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM profile.ide_repository '
                'WHERE thread_id=:tid'),{'tid':thread})==4
            assert await connection.scalar(text('SELECT onboarding_created '
                'FROM profile.ide_repository '
                'WHERE repository_id=:id'),{'id':destination}) is False
        clone_cases += 1
        claims = await asyncio.gather(*(clones.claim(**identity) for _ in range(8)))
        assert sum(claims)==1
        started = await fresh_clones.get_owned(**identity)
        assert started['state']=='cloning' and started['started_at']>0
        dispatch_args = dict(thread_id=thread,user_id=owner,repository_id=destination,
            intent_id=clone_id)
        assert await repository.clone_dispatch_owned(**dispatch_args)
        assert not await repository.clone_dispatch_owned(**{**dispatch_args,'user_id':other})
        assert not await repository.clone_dispatch_owned(
            **{**dispatch_args,'intent_id':uuid.uuid4()})
        clone_cases += 1
        await clones.finish(**identity,state='complete',code=None)
        assert not await fresh_clones.claim(**identity)
        assert (await clones.get_owned(**identity))['state']=='complete'
        assert not await repository.clone_dispatch_owned(**dispatch_args)
        clone_cases += 1
        await clones.finish(**identity,state='unconfirmed',code='ide_git_unconfirmed')
        assert (await clones.get_owned(**identity))['state']=='complete'
        clone_cases += 1
        stage = 'migration_downgrade'
        def downgrade(connection):
            with Operations.context(MigrationContext.configure(connection)):
                recovery_migration.downgrade()
                clone_migration.downgrade()
                starter_migration.downgrade()
                runtime_migration.downgrade()
                migration.downgrade()
        async with engine.begin() as connection:
            await connection.run_sync(downgrade)
            table = await connection.scalar(text("SELECT to_regclass('profile.ide_repository')"))
            assert table is None
        cases += 1
    except BaseException:
        failure_stage = stage
        raise
    else:
        failure_stage = None
    finally:
        stage = 'fixture_cleanup'
        if engine is not None:
            await engine.dispose()
        if created:
            await admin.execute('DROP DATABASE "' + database + '"')
            assert not await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', database)
        await admin.close()
        if failure_stage is not None:
            stage = failure_stage
    print(json.dumps({'cases':cases,'runtime_cases':runtime_cases,
        'onboarding_cases':onboarding_cases,'clone_cases':clone_cases,
        'recovery_cases':recovery_cases,'fixture_removed':True}))

try:
    asyncio.run(main())
except BaseException:
    print(json.dumps({'status':'failed','stage':stage}))
    raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_IDE_DESCRIPTORS") != "1",
    reason="explicit isolated PostgreSQL descriptor acceptance",
)
def test_real_postgres_migration_ownership_parallel_intents_and_pagination():
    root = Path(__file__).resolve().parents[1]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in _FILES}
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps({"files": files}),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"isolated_descriptor_probe_failed: {result.stdout.strip()}"
    assert json.loads(result.stdout) == {
        "cases": 14,
        "runtime_cases": 9,
        "onboarding_cases": 9,
        "clone_cases": 8,
        "recovery_cases": 2,
        "fixture_removed": True,
    }
