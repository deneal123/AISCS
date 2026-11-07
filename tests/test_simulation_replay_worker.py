import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks
from service.services.simulations.models import SimulationArtifact
from tests.test_simulation_replay_manifest import preview


@pytest.mark.asyncio
@pytest.mark.parametrize('tampered', [False, True])
async def test_worker_stages_replay_and_publishes_verified_preview(monkeypatch, tampered):
    run_id, attempt, owner, source_id = uuid4(), uuid4(), uuid4(), uuid4()
    digest = 'a' * 64
    payload = {'source_run_id': str(source_id), 'graph_manifest_sha256': 'b' * 64,
               'body_id': 42, 'simulation': {'duration_ms': 2., 'dt_ms': 1.}}
    run = SimpleNamespace(id=run_id, user_id=owner, attempt_id=attempt, job_id=uuid4(),
                          state='queued', execution_queue='simulation', lease_until=None,
                          configuration=payload,
                          configuration_sha256=digest, claim_token=None)
    job, saved_rows = SimpleNamespace(status=None), []

    class Session:
        async def execute(self, statement):
            value = None if 'simulation_artifact' in str(statement) else run
            return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value)

        async def get(self, *_args):
            return job

        def add(self, value):
            saved_rows.append(value)

        async def commit(self):
            pass

    @asynccontextmanager
    async def session_context():
        yield Session()

    connector = SimpleNamespace(get_session_context=session_context, close=AsyncMock())
    infra = SimpleNamespace(pg_connector=connector, redis_client=None, storage=object())
    monkeypatch.setattr(tasks, 'build_infra', lambda _config: infra)
    monkeypatch.setattr(tasks, 'emit', AsyncMock())
    source = SimpleNamespace(sha256='c' * 64, description={'manifest_sha256': 'b' * 64})
    monkeypatch.setattr(tasks, 'owned_replay_source', AsyncMock(return_value=source))
    stage = AsyncMock()
    monkeypatch.setattr(tasks, 'stage_replay_input', stage)
    ack = AsyncMock()
    monkeypatch.setattr(tasks, 'acknowledge_result', ack)
    reject = AsyncMock()
    monkeypatch.setattr(tasks, 'reject_result', reject)
    publications = []

    async def touch(_infra, _id, _token, state=None, result=None, **_kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        return False

    monkeypatch.setattr(tasks, 'touch', touch)
    files = {'replay-evidence.json': b'evidence', 'replay-signal.npz': b'signal',
             'replay-preview.json': json.dumps(preview(), ensure_ascii=False).encode()}
    manifest = {'format': 'independent-swc-replay-artifact-v1', 'kind': 'independent-cell-replay',
                'configuration_sha256': digest, 'source_run_id': str(source_id),
                'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'stimulus_artifact_uv': 'µV',
                          'total_uv': 'µV'},
                'files': [{'name': name, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()]}

    preview_requests = 0

    async def handler(request):
        nonlocal preview_requests
        if request.method == 'POST':
            assert request.url.path == '/v1/replay-executions'
            body = json.loads(await request.aread())
            assert body['source_sha256'] == source.sha256
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest})
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'replay-preview.json':
            preview_requests += 1
            if tampered and preview_requests == 2:
                return httpx.Response(200, content=b'tampered')
        return httpx.Response(200, content=files[name])

    @asynccontextmanager
    async def client_factory():
        async with httpx.AsyncClient(base_url='http://generator',
                                     transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(tasks, 'generator_client', client_factory)

    async def save(_owner, _kind, name, chunks, **kwargs):
        await kwargs['before_persist']()
        data = b''.join([part async for part in chunks])
        assert data == files[name]
        assert hashlib.sha256(data).hexdigest() == kwargs['expected_sha256']
        return SimpleNamespace(file_id=uuid4())

    monkeypatch.setattr(tasks, 'file_service', lambda _infra: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    stage.assert_awaited_once()
    assert {row.name for row in saved_rows if isinstance(row, SimulationArtifact)} == set(files)
    if tampered:
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_integrity'
    else:
        assert run.state == 'completed'
        assert publications[0]['preview']['body_id'] == '42'
        ack.assert_awaited_once()
        reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_rejects_response_exceeding_manifest_size():
    async def handler(_request):
        return httpx.Response(200, content=b'12345')

    async with httpx.AsyncClient(base_url='http://generator',
                                 transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(tasks.InvalidManifest, match='preview_integrity'):
            await tasks.read_verified_preview(client, uuid4(), 'replay-preview.json', {
                'bytes': 4, 'sha256': hashlib.sha256(b'1234').hexdigest(),
            })
