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
@pytest.mark.parametrize('tamper', [False, True])
async def test_full_feedback_worker_checks_and_publishes(tmp_path, monkeypatch, tamper):
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    synapse = {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    payload = {'graph_manifest_sha256': 'a' * 64, 'simulation': {'duration_ms': 10, 'dt_ms': 1},
        'excitatory': synapse, 'inhibitory': {**synapse, 'reversal_mv': -80.},
        'threshold_mv': -20., 'max_source_distance_um': 2., 'max_target_distance_um': 2.,
        'max_iterations': 3, 'max_events': 100, 'allow_known_geometry_repair': False}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                            separators=(',', ':')).encode()).hexdigest()
    numerical = {'graph_sha256': 'a' * 64, 'request_sha256': digest,
        **{key: payload[key] for key in ('simulation', 'threshold_mv', 'max_source_distance_um',
                                         'max_target_distance_um', 'max_iterations', 'max_events')},
        'synapse_parameters': {'1': payload['excitatory'], '-1': payload['inhibitory']},
        'geometry_repair': None}
    numerical_hash = hashlib.sha256(json.dumps(numerical, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()
    preview = {'kind': 'experimental-full-population-feedback', 'status': 'converged',
        'graph_cells': 2, 'source_cells': 2, 'duration_ms': 10, 'iterations': 1,
        'control_iterations': 1,
        'candidate_cell_time_markers': 1, 'timeline': {'samples': 11, 'shown_samples': 2,
            'time_ms': [0., 10.], 'neural_uv': [0., 1.], 'control_uv': [0., 0.],
            'stimulus_fraction': [0., 0.],
            'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'control_uv': 'µV'}}}
    files = {name: name.encode() for name in ('initial-active.jsonl', 'control.jsonl',
        'activity.jsonl', 'signals.npz', 'coupled-source-events.bin')}
    files['preview.json'] = json.dumps(preview).encode()
    entries = [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
               for name, data in files.items()]
    manifest = {'kind': preview['kind'], 'status': 'converged', 'graph_sha256': 'a' * 64,
        'configuration_sha256': numerical_hash, 'configuration': numerical, 'cells': 2,
        'iterations': 1, 'control_iterations': 1,
        'control_feedback_schedule_sha256': 'c' * 64, 'files': entries,
        'file_hashes': {item['name']: item['sha256'] for item in entries}}
    run = SimpleNamespace(id=run_id, user_id=owner, parent_run_id=None, attempt_id=attempt,
        job_id=uuid4(), state='queued', execution_queue='simulation', lease_until=None,
        configuration=payload, configuration_sha256=digest, claim_token=None)
    job, publications = SimpleNamespace(status=None), []

    class Session:
        async def execute(self, statement):
            value = None if 'simulation_artifact' in str(statement) else run
            return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value)

        async def get(self, *_args):
            return job

        def add(self, _value):
            pass

        async def commit(self):
            pass

    @asynccontextmanager
    async def session():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session,
        close=AsyncMock()), redis_client=None, storage=object())
    monkeypatch.setattr(tasks, 'build_infra', lambda _: infra)
    monkeypatch.setattr(tasks, 'emit', AsyncMock())
    ack, reject = AsyncMock(), AsyncMock()
    monkeypatch.setattr(tasks, 'acknowledge_result', ack)
    monkeypatch.setattr(tasks, 'reject_result', reject)

    async def touch(_infra, _id, _token, state=None, result=None, **_kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        return False

    monkeypatch.setattr(tasks, 'touch', touch)
    preview_calls = 0

    async def handler(request):
        nonlocal preview_calls
        if request.method == 'POST':
            if request.url.path.endswith('-validate'):
                return httpx.Response(200, json={'configuration_sha256': digest, 'graph_cells': 2})
            assert request.url.path == '/v1/full-population-feedback-executions'
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest})
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'preview.json':
            preview_calls += 1
            if tamper and preview_calls == 2:
                return httpx.Response(200, content=b'tampered')
        return httpx.Response(200, content=files[name])

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url='http://generator') as instance:
            yield instance

    monkeypatch.setattr(tasks, 'generator_client', client)

    async def save(_owner, _kind, _name, chunks, **kwargs):
        await kwargs['before_persist']()
        data = b''.join([part async for part in chunks])
        assert hashlib.sha256(data).hexdigest() == kwargs['expected_sha256']
        return SimpleNamespace(file_id=uuid4())

    monkeypatch.setattr(tasks, 'file_service', lambda _: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    if tamper:
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_integrity'
    else:
        assert publications[0]['preview'] == preview
        assert run.state == 'completed'
        ack.assert_awaited_once()
        reject.assert_not_awaited()
