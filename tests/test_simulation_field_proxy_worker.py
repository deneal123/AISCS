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
@pytest.mark.parametrize('corrupt_preview', [False, True])
async def test_field_proxy_worker_publishes_only_verified_model_events(
    monkeypatch, corrupt_preview
):
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    digest = 'a' * 64
    config = {'gain': 1.0, 'waveform': [0.0, 1.0],
              'coordinate_frame': 'male-cns-v1.0-native-um'}
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
    monkeypatch.setattr(tasks, 'build_infra', lambda _config: infra)
    emit = AsyncMock()
    monkeypatch.setattr(tasks, 'emit', emit)
    ack, reject = AsyncMock(), AsyncMock()
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
    preview = {'kind': 'experimental-field-proxy', 'duration_ms': 2, 'time_step_ms': 1.0,
               'neurons': 3, 'spike_count': 2, 'active_neurons': 1,
               'spikes_by_ms': [0, 1, 1], 'control_spikes_by_ms': [0, 0, 1],
               'direct_field_exclusions': 0,
               'contact_exclusions': 0, 'recording': None}
    if corrupt_preview:
        preview['recording'] = [1, 2]
    files = {name: b'data' for name in ('metadata.json', 'network.npz',
             'network-events.bin', 'network-control-events.bin', 'state-response.bin')}
    files['field-proxy-preview.json'] = json.dumps(preview).encode()
    manifest = {'format': 'field-proxy-manifest-v1', 'kind': 'experimental-field-proxy',
        'configuration_sha256': digest, 'files': [{'name': name, 'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()]}

    async def handler(request):
        if request.method == 'POST':
            assert request.url.path == '/v1/field-proxy-executions'
            assert json.loads(request.content)['config'] == config
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest,
                'progress': {'phase': 'network', 'done': 2, 'total': 2}})
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
        assert len(data) == kwargs['expected_size']
        assert hashlib.sha256(data).hexdigest() == kwargs['expected_sha256']
        return SimpleNamespace(file_id=uuid4())

    monkeypatch.setattr(tasks, 'file_service', lambda _infra: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    assert any(call.kwargs.get('progress') == {'phase': 'network', 'done': 2, 'total': 2}
               and call.args[1] == run_id for call in emit.await_args_list)
    if corrupt_preview:
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_invalid'
    else:
        assert publications[0]['preview'] == preview
        assert run.state == 'completed'
        ack.assert_awaited_once()
        reject.assert_not_awaited()
