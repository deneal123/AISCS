"""Opt-in PDF preparation claim proof in an isolated disposable database."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILES = (
    "alembic/versions/038_pdf_preparation.py",
    "service/services/chat/domain/documents/preparation.py",
    "service/services/chat/persistence/documents/preparation.py",
)
_PROBE = r"""
import asyncio, hashlib, importlib.util, json, logging, re, sys, uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from service.settings import config
from service.services.chat.domain.documents.preparation import PdfPreparationScope
from service.services.chat.persistence.documents.preparation import PdfPreparationRepository

stage = 'source_parity'
async def main():
    global stage
    files = json.load(sys.stdin)['files']
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path,digest in files.items())
    assert config.pg.host == 'postgres'
    database = 'gpthub_pdf_test_' + uuid.uuid4().hex[:24]
    assert re.fullmatch(r'gpthub_pdf_test_[0-9a-f]{24}', database)
    admin = await asyncpg.connect(host=config.pg.host, port=config.pg.port,
        user=config.pg.user, password=config.pg.password, database=config.pg.db, timeout=5)
    created, engine, cases = False, None, 0
    failure_stage = None
    try:
        stage = 'fixture_allocation'
        await admin.execute('CREATE DATABASE "' + database + '"')
        created = True
        engine = create_async_engine(URL.create('postgresql+asyncpg', host=config.pg.host,
            port=config.pg.port, username=config.pg.user, password=config.pg.password,
            database=database),echo=False)
        spec = importlib.util.spec_from_file_location('pdf_migration',
            'alembic/versions/038_pdf_preparation.py')
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        stage = 'migration_upgrade'
        async with engine.begin() as conn:
            await conn.execute(text('CREATE SCHEMA profile'))
            await conn.execute(text('CREATE TABLE profile.chat_threads (thread_id uuid PRIMARY KEY,'
                'user_id uuid NOT NULL,title text,created_at timestamptz,updated_at timestamptz)'))
            def upgrade(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
            await conn.run_sync(upgrade)
        sessions = async_sessionmaker(engine,expire_on_commit=False)
        class Connector:
            def get_session_context(self): return sessions()
        repository = PdfPreparationRepository(Connector())
        scope = PdfPreparationScope(uuid.uuid4(),uuid.uuid4())
        stage = 'parallel_claim'
        assert all(await asyncio.gather(*(repository.ensure_owner(scope) for _ in range(8))))
        claims = await asyncio.gather(*(repository.claim(scope,ttl_sec=300) for _ in range(16)))
        assert sum(dispatch for _,dispatch in claims)==1
        identity = claims[0][0]
        assert all(value==identity for value,_ in claims)
        cases += 1
        stage = 'process_reentry'
        fresh = PdfPreparationRepository(Connector())
        assert await fresh.claim(scope,ttl_sec=999)==(identity,False)
        cases += 1
        stage = 'ownership'
        denied = PdfPreparationScope(scope.thread_id,uuid.uuid4())
        assert not await fresh.ensure_owner(denied)
        assert await fresh.get_owned(denied) is None
        assert await fresh.claim(denied,ttl_sec=300)==(None,False)
        cases += 1
        stage = 'adopt_existing'
        adopted_scope = PdfPreparationScope(uuid.uuid4(),scope.user_id)
        assert await repository.ensure_owner(adopted_scope)
        adopted,dispatch = await repository.claim(adopted_scope,ttl_sec=1,
            workspace_id='a'*32,expires_at=identity.expires_at)
        assert not dispatch and adopted.allocation_id is None and adopted.workspace_id=='a'*32
        cases += 1
        stage = 'scaffold_dispatch'
        claims = await asyncio.gather(*(fresh.claim_scaffold(adopted_scope) for _ in range(16)))
        assert sum(claims)==1
        assert not await fresh.claim_scaffold(adopted_scope,allow_retry=True)
        await fresh.reject_scaffold(adopted_scope)
        assert not await fresh.claim_scaffold(adopted_scope)
        assert await fresh.claim_scaffold(adopted_scope,allow_retry=True)
        assert await fresh.observe_project(adopted_scope)
        await fresh.reject_scaffold(adopted_scope)
        assert not await fresh.claim_scaffold(adopted_scope,allow_retry=True)
        assert (await fresh.get_owned(adopted_scope)).scaffold_state=='observed'
        assert not await fresh.claim_scaffold(denied,allow_retry=True)
        cases += 1
        stage = 'expired_reentry'
        async with engine.begin() as conn:
            await conn.execute(text('UPDATE profile.pdf_preparation SET expires_at=1 '
                'WHERE thread_id=:id'),{'id':scope.thread_id})
        expired,dispatch = await fresh.claim(scope,ttl_sec=300)
        assert not dispatch and expired.expires_at==1
        assert expired.allocation_id==identity.allocation_id
        cases += 1
        stage = 'migration_downgrade'
        async with engine.begin() as conn:
            def downgrade(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migration.downgrade()
            await conn.run_sync(downgrade)
            assert await conn.scalar(text("SELECT to_regclass('profile.pdf_preparation')")) is None
        cases += 1
    except BaseException:
        failure_stage = stage
        raise
    finally:
        stage = 'fixture_cleanup'
        if engine is not None: await engine.dispose()
        if created:
            assert re.fullmatch(r'gpthub_pdf_test_[0-9a-f]{24}', database)
            await admin.execute('DROP DATABASE "' + database + '"')
            assert not await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',database)
        await admin.close()
        if failure_stage is not None: stage=failure_stage
    print(json.dumps({'cases':cases,'fixture_removed':True}))
try:
    asyncio.run(main())
except BaseException:
    print(json.dumps({'status':'failed','stage':stage}))
    raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PDF_PREPARATION") != "1", reason="isolated PDF PostgreSQL proof"
)
def test_parallel_first_entry_ownership_expiry_and_migration():
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
    assert result.returncode == 0, f"isolated_pdf_preparation_failed: {result.stdout.strip()}"
    assert json.loads(result.stdout) == {"cases": 7, "fixture_removed": True}
