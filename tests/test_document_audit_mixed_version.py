"""A legacy router ignoring unknown fields must never receive recovery POSTs."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from service.infrastructure.agents_client.document_audit import client as audit
from service.infrastructure.agents_client.document_audit import recovery as recovery
from service.infrastructure.sidecar import SidecarClient


@pytest.mark.asyncio
async def test_old_extra_ignoring_router_cannot_execute_versioned_recovery_or_stream(monkeypatch):
    app = FastAPI()
    invoked = []

    class OldRequest(BaseModel):
        build_id: str
        workspace_ref: dict

    @app.post("/document-audit")
    async def old_execute(payload: OldRequest):
        invoked.append(True)
        return {"status": "passed", "passed": True, "retryable": False}

    def client_factory(**kwargs):
        return SidecarClient(**kwargs, transport=httpx.ASGITransport(app=app))

    monkeypatch.setattr(audit, "SidecarClient", client_factory)
    monkeypatch.setattr(recovery, "SidecarClient", client_factory)
    monkeypatch.setattr(audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(audit.provider_policy, "blocked_providers", AsyncMock(return_value=()))
    from types import SimpleNamespace

    config = SimpleNamespace(
        agents=SimpleNamespace(sidecar_url="http://legacy", llm_gateway_api_key="")
    )
    attempt = uuid4()
    # Reproduce the dangerous old-path behavior without any real provider call.
    original = client_factory(service="agents", base_url="http://legacy", timeout=1)
    await original.request_json(
        "POST",
        "/document-audit",
        json_body={
            "build_id": "fixture-build",
            "workspace_ref": {},
            "recovery_only": True,
            "checkpoint_attempt_id": str(attempt),
        },
    )
    assert invoked == [True]
    invoked.clear()

    recovered = await recovery.recover_document_audit(
        config, workspace_ref={}, build_id="fixture-build", attempt_id=attempt
    )
    assert recovered.state == "unavailable"
    fresh = await audit.audit_document(
        config,
        workspace_ref={},
        build_id="fixture-build",
        checkpoint_attempt_id=attempt,
        checkpoint_sink=AsyncMock(),
        fresh_attempt=True,
    )
    assert fresh["producer_unresolved"] is True and not fresh["passed"]
    assert invoked == []
