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
@pytest.mark.parametrize("tampered", [False, True])
async def test_field_graph_validation_binds_response_to_request(monkeypatch, tampered):
    requested = {
        "source_cells": [{"body_id": 10}],
        "replay_ids": [20],
        "acquisition": {"clip_uv": None, "low_hz": 10},
    }
    normalized = {
        "source_cells": [{"body_id": 11 if tampered else 10}],
        "replay_ids": [20],
        "acquisition": {"low_hz": 10},
    }
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    response = httpx.Response(
        200,
        json={"configuration": normalized, "configuration_sha256": digest},
        request=httpx.Request("POST", "http://g/test"),
    )
    post = AsyncMock(return_value=response)

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(api, "generator_client", factory)
    create = AsyncMock(return_value={"id": "queued"})
    monkeypatch.setattr(api, "create_checked_run", create)
    payload = api.RunCreate(request_id=uuid4(), configuration=requested)
    if tampered:
        with pytest.raises(HTTPException) as error:
            await api.create_field_graph_run(payload, SimpleNamespace(user_id=uuid4()))
        assert error.value.status_code == 503
        create.assert_not_awaited()
    else:
        assert await api.create_field_graph_run(payload, SimpleNamespace(user_id=uuid4())) == {
            "id": "queued"
        }
        create.assert_awaited_once()
    assert post.await_args.args[0] == "/v1/field-graph-validate"
