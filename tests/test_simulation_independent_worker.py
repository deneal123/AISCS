import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('corrupt', [False, True])
async def test_independent_worker_publishes_only_verified_recording(monkeypatch, corrupt):
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    digest = 'a' * 64
    config = {'graph_manifest_sha256': 'b' * 64, 'simulation': {'duration_ms': .1}}
    run = SimpleNamespace(id=run_id, user_id=owner, attempt_id=attempt, job_id=uuid4(),
        state='queued', execution_queue='simulation', lease_until=None, configuration=config,
        configuration_sha256=digest, claim_token=None, parent_run_id=None)
    job = SimpleNamespace(status=None)

    class Session:
        async def execute(self, statement):
            row = None if 'simulation_artifact' in str(statement) else run
            return SimpleNamespace(scalar_one_or_none=lambda: row, scalar_one=lambda: row)

        async def get(self, *_args):
            return job

        def add(self, _row):
            pass

        async def commit(self):
            pass

    @asynccontextmanager
    async def session_context():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context,
        close=AsyncMock()), redis_client=None, storage=object())
    monkeypatch.setattr(tasks, 'build_infra', lambda _: infra)
    emit, ack, reject = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(tasks, 'emit', emit)
    monkeypatch.setattr(tasks, 'acknowledge_result', ack)
    monkeypatch.setattr(tasks, 'reject_result', reject)
    publications = []

    async def touch(_infra, _id, _token, state=None, result=None, **_kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        return False

    monkeypatch.setattr(tasks, 'touch', touch)
    preview = {'kind': 'experimental-independent-population', 'cells': 166700,
        'samples': 3, 'shown_samples': 3, 'replacement_count': 1,
        'interpretation': 'no network feedback', 'units': {'time_ms': 'ms', 'neural_uv': 'µV'},
        'time_ms': [0., .05, .1], 'neural_uv': [0., 1., -1.]}
    if corrupt:
        preview['time_ms'][-1] = .2
    files = {'recording.npz': b'data', 'preview.json': json.dumps(preview).encode()}
    manifest = {'format': 'independent-gpu-recording-v1',
        'kind': 'experimental-independent-population', 'configuration_sha256': digest,
        'geometry_cache_manifest_sha256': 'c' * 64, 'source_index_sha256': 'd' * 64,
        'geometry_repair_policy': 'verified-842998', 'interpretation': 'no network feedback',
        'files': [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in files.items()]}

    async def handler(request):
        if request.method == 'POST':
            assert request.url.path == '/v1/independent-population-executions'
            assert json.loads(request.content)['config'] == config
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest,
                'progress': {'phase': 'independent_cells', 'done': 166700, 'total': 166700}})
        return httpx.Response(200, content=files[request.url.path.rsplit('/', 1)[-1]])

    @asynccontextmanager
    async def client_factory():
        async with httpx.AsyncClient(base_url='http://generator',
                                    transport=httpx.MockTransport(handler)) as client:
            yield client

    monkeypatch.setattr(tasks, 'generator_client', client_factory)

    async def save(_owner, _kind, _name, chunks, **kwargs):
        await kwargs['before_persist']()
        data = b''.join([part async for part in chunks])
        assert hashlib.sha256(data).hexdigest() == kwargs['expected_sha256']
        assert len(data) == kwargs['expected_size']
        return SimpleNamespace(file_id=uuid4())

    monkeypatch.setattr(tasks, 'file_service', lambda _: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    assert any(call.kwargs.get('progress', {}).get('phase') == 'independent_cells'
               for call in emit.await_args_list)
    if corrupt:
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_invalid'
    else:
        assert publications[0]['preview'] == preview
        assert run.state == 'completed'
        ack.assert_awaited_once()
