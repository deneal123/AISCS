import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api


@pytest.mark.asyncio
@pytest.mark.parametrize('tampered', [False, True])
async def test_independent_run_binds_validation_to_configuration(monkeypatch, tampered):
    configuration = {'graph_manifest_sha256': 'a' * 64, 'simulation': {'current_na': -300.}}
    normalized = {**configuration, 'graph_manifest_sha256': ('b' if tampered else 'a') * 64}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode('utf8')).hexdigest()
    response = httpx.Response(200, json={'configuration': normalized,
                                       'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://generator/test'))
    post = AsyncMock(return_value=response)

    @asynccontextmanager
    async def client():
        yield SimpleNamespace(post=post)

    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'generator_client', client)
    monkeypatch.setattr(api, 'create_checked_run', create)
    request = api.RunCreate(request_id=uuid4(), configuration=configuration)
    if tampered:
        with pytest.raises(HTTPException) as exc:
            await api.create_run(request, SimpleNamespace(user_id=uuid4()))
        assert exc.value.status_code == 503
        create.assert_not_awaited()
    else:
        assert await api.create_run(request, SimpleNamespace(user_id=uuid4())) == {'id': 'queued'}
        create.assert_awaited_once()
    assert post.await_args.args[0] == '/v1/independent-population-validate'
