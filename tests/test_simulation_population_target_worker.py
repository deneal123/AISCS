import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks
from tests.test_simulation_population_target_manifest import preview


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', [False, True])
async def test_target_worker_publishes_only_verified_preview(monkeypatch, tamper):
    run_id, attempt, owner, parent = uuid4(), uuid4(), uuid4(), uuid4()
    payload = {'graph_manifest_sha256': 'a' * 64, 'source_package_sha256': 'b' * 64,
               'source_manifest_sha256': 'c' * 64, 'target_id': 20, 'source_ids': [10, 11],
               'duration_ms': 2, 'max_events': 10}
    run = SimpleNamespace(id=run_id, user_id=owner, parent_run_id=parent, attempt_id=attempt,
        job_id=uuid4(), state='queued', execution_queue='simulation', lease_until=None,
        configuration=payload, configuration_sha256='d' * 64, claim_token=None)
    job, rows, publications = SimpleNamespace(status=None), [], []
    class Session:
        async def execute(self, statement):
            value = None if 'simulation_artifact' in str(statement) else run
            return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value)
        async def get(self, *_args):
            return job
        def add(self, value):
            rows.append(value)
        async def commit(self):
            pass
    @asynccontextmanager
    async def session():
        yield Session()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session,
        close=AsyncMock()), redis_client=None, storage=object())
    monkeypatch.setattr(tasks, 'build_infra', lambda _: infra)
    monkeypatch.setattr(tasks, 'emit', AsyncMock())
    source = SimpleNamespace(configuration={'simulation': {'dt_ms': 1.}, 'source_ids': [10, 11]})
    resolve = AsyncMock(return_value=source)
    stage, ack, reject = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(tasks, 'owned_fragment_source', resolve)
    monkeypatch.setattr(tasks, 'stage_target_with_lease', stage)
    monkeypatch.setattr(tasks, 'acknowledge_result', ack)
    monkeypatch.setattr(tasks, 'reject_result', reject)
    async def touch(_infra, _id, _token, state=None, result=None, **_kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        return False
    monkeypatch.setattr(tasks, 'touch', touch)
    files = {'target-model.json': b'model', 'target-signals.npz': b'signals',
             'target-preview.json': json.dumps(preview(), ensure_ascii=False).encode()}
    manifest = {'kind': 'experimental-one-way-target-replay', 'configuration_sha256': 'd' * 64,
        'files': [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in files.items()]}
    preview_calls = 0
    async def handler(request):
        nonlocal preview_calls
        if request.method == 'POST':
            assert request.url.path == '/v1/population-target-executions'
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest})
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'target-preview.json':
            preview_calls += 1
            if tamper and preview_calls == 2:
                return httpx.Response(200, content=b'tampered')
        return httpx.Response(200, content=files[name])
    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url='http://generator') as result:
            yield result
    monkeypatch.setattr(tasks, 'generator_client', client)
    async def save(_owner, _kind, _name, chunks, **kwargs):
        await kwargs['before_persist']()
        data = b''.join([part async for part in chunks])
        assert hashlib.sha256(data).hexdigest() == kwargs['expected_sha256']
        return SimpleNamespace(file_id=uuid4())
    monkeypatch.setattr(tasks, 'file_service', lambda _: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    stage.assert_awaited_once()
    assert resolve.await_args.args[1:] == (owner, parent, 'a' * 64)
    if tamper:
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_integrity'
    else:
        assert publications[0]['preview']['target_id'] == 20
        assert run.state == 'completed'
        ack.assert_awaited_once()
        reject.assert_not_awaited()
