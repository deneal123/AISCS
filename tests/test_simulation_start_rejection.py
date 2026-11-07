import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks


@pytest.mark.parametrize('probe,expected', [
    ('missing', 'executor_contract_rejected'),
    ('mismatch', 'executor_attempt_identity'),
    ('existing', 'executor_contact_clearance'),
    ('unavailable', None),
])
@pytest.mark.parametrize('start_status', [404, 422])
def test_rejected_start_checks_existing_attempt_before_terminal_failure(
    monkeypatch, probe, expected, start_status,
):
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    digest = 'a' * 64
    run = SimpleNamespace(id=run_id, user_id=owner, attempt_id=attempt, job_id=uuid4(),
                          state='queued', execution_queue='simulation', lease_until=None,
                          configuration={}, configuration_sha256=digest, claim_token=None)
    job = SimpleNamespace(status=None)

    class Session:
        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: run)

        async def get(self, *_args):
            return job

        async def commit(self):
            pass

    @asynccontextmanager
    async def session_context():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context,
                                                         close=AsyncMock()), redis_client=None)
    monkeypatch.setattr(tasks, 'build_infra', lambda _config: infra)
    monkeypatch.setattr(tasks, 'simulation_queue', lambda: 'simulation')
    monkeypatch.setattr(tasks, 'emit', AsyncMock())
    touch = AsyncMock(return_value=False)
    monkeypatch.setattr(tasks, 'touch', touch)
    discard = AsyncMock()
    monkeypatch.setattr(tasks, 'discard_unpublished', discard)

    async def handler(request):
        if request.method == 'POST':
            return httpx.Response(start_status, json={'detail': 'private diagnostics'})
        if probe == 'missing':
            return httpx.Response(404)
        if probe == 'unavailable':
            return httpx.Response(503)
        if probe == 'mismatch':
            return httpx.Response(200, json={'configuration_sha256': 'b' * 64})
        return httpx.Response(200, json={'configuration_sha256': digest, 'status': 'failed',
            'error': {'type': 'ValueError',
                      'message': 'Contact exclusion sphere intersects a cable segment'}})

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url='http://generator') as session:
            yield session

    monkeypatch.setattr(tasks, 'generator_client', client)
    asyncio.run(tasks.execute(run_id))
    errors = [call.kwargs.get('error') for call in touch.await_args_list
              if call.kwargs.get('error')]
    if expected:
        if expected == 'executor_contract_rejected' and start_status == 404:
            expected = 'executor_endpoint_missing'
        assert errors == [expected]
    else:
        assert not errors and run.error == 'temporary_execution_or_publication_failure'
    if probe in ('missing', 'mismatch', 'unavailable'):
        discard.assert_not_awaited()
    else:
        discard.assert_awaited_once()
