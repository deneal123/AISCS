"""Private v2 route admission cannot accidentally fall through to legacy work."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from service.presentation.routers.capabilities import document_audit as endpoint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{}, {"checkpoint_attempt_id": str(uuid4())}, {"fresh_attempt": True}]
)
async def test_invalid_v2_admission_does_not_execute_legacy_audit(monkeypatch, body):
    monkeypatch.setattr(endpoint, "internal_auth", lambda _: None)
    execute = AsyncMock()
    monkeypatch.setattr(endpoint, "_execute_audit", execute)
    app = FastAPI()
    app.include_router(endpoint.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.post(
            "/document-audit/v2",
            json={
                "build_id": "fixture-build",
                "workspace_ref": {},
                **body,
            },
        )
    assert response.status_code == 200 and response.json()["status"] == "protocol"
    execute.assert_not_awaited()
