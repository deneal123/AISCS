import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks
from tests.test_simulation_population_feedback import sample


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['valid', 'tamper', 'unconverged'])
@pytest.mark.parametrize('source_markers', [False, True])
async def test_feedback_worker_publishes_only_verified_result(monkeypatch, outcome, source_markers):
    run_id, attempt, owner, parent = uuid4(), uuid4(), uuid4(), uuid4()
    payload, manifest, preview = sample()
    payload.update(excitatory={}, inhibitory={})
    run = SimpleNamespace(id=run_id, user_id=owner, parent_run_id=parent, attempt_id=attempt,
        job_id=uuid4(), state='queued', execution_queue='simulation', lease_until=None,
        configuration=payload, configuration_sha256='d' * 64, claim_token=None)
    job, rows, publications, failures = SimpleNamespace(status=None), [], [], []
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
    source = SimpleNamespace(configuration={'source_ids': [10, 20],
        'simulation': {'duration_ms': 10, 'dt_ms': 1}})
    resolve, stage, ack, reject = (AsyncMock(return_value=source), AsyncMock(),
                                   AsyncMock(), AsyncMock())
    monkeypatch.setattr(tasks, 'owned_fragment_source', resolve)
    monkeypatch.setattr(tasks, 'stage_target_with_lease', stage)
    monkeypatch.setattr(tasks, 'acknowledge_result', ack)
    monkeypatch.setattr(tasks, 'reject_result', reject)
    async def touch(_infra, _id, _token, state=None, result=None, **kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        if kwargs.get('error'):
            failures.append(kwargs['error'])
        return False
    monkeypatch.setattr(tasks, 'touch', touch)
    files = {'coupled-population.zip': b'archive',
             'coupled-preview.json': json.dumps(preview, ensure_ascii=False).encode(),
             'coupled-delta.bin': b'delta', 'coupled-events.bin': b'events'}
    if source_markers:
        files['coupled-source-events.bin'] = b'source-events'
    manifest['files'] = [{'name': name, 'bytes': len(data),
                          'sha256': hashlib.sha256(data).hexdigest()}
                         for name, data in files.items()]
    preview_calls = 0
    async def handler(request):
        nonlocal preview_calls
        if request.method == 'POST':
            if request.url.path.endswith('/discard'):
                return httpx.Response(200, json={})
            assert request.url.path == '/v1/population-feedback-executions'
            return httpx.Response(200, json={'status': 'running'})
        if request.url.path.endswith(str(attempt)):
            if outcome == 'unconverged':
                return httpx.Response(200, json={'status': 'failed', 'error': {
                    'type': 'ValueError',
                    'message': 'Coupled feedback did not converge: iteration_limit',
                    'feedback_diagnostics': {'status': 'iteration_limit', 'history': [{
                        'iteration': 1, 'input_events': 2, 'unresolved_events': 0,
                        'outside_window': 0, 'output_edge_records': 1, 'network_spikes': 0}]}}})
            return httpx.Response(200, json={'status': 'completed', 'manifest': manifest})
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'coupled-preview.json':
            preview_calls += 1
            if outcome == 'tamper' and preview_calls == 2:
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
    if outcome == 'unconverged':
        assert run.state == 'failed'
        assert failures == ['executor_feedback_iteration_limit']
        assert publications[0]['feedback_failure']['history'][0]['input_events'] == 2
        assert 'preview' not in publications[0]
        ack.assert_not_awaited()
    elif outcome == 'tamper':
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == 'preview_integrity'
    else:
        assert publications[0]['preview']['graph_cells'] == 166700
        assert run.state == 'completed'
        ack.assert_awaited_once()
        reject.assert_not_awaited()
