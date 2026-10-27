import json
import time
from unittest.mock import AsyncMock

import pytest

from service.infrastructure import pdf_workspace_binding as module
from service.services.chat.domain.documents.preparation import PdfPreparationUnavailable


@pytest.mark.asyncio
async def test_binding_publish_is_create_only_and_rechecks_exact_observed_identity(monkeypatch):
    ref = {
        "thread_id": "thread",
        "user_id": "owner",
        "workspace_id": "a" * 32,
        "expires_at": int(time.time()) + 100,
        "token": "PRIVATE",
    }
    call = AsyncMock(return_value=True)
    read = AsyncMock(return_value=("ready", ref))
    monkeypatch.setattr(module.workspace_client, "_redis_call", call)
    monkeypatch.setattr(module.workspace_client, "read_binding_state", read)
    redis = object()
    assert await module.publish_pdf_binding(redis, ref) == ref
    args, kwargs = call.await_args
    assert args[0] is redis and args[1] == "set" and json.loads(args[3]) == ref
    assert kwargs["nx"] is True and 1 <= kwargs["ex"] <= 100
    read.return_value = ("ready", {**ref, "workspace_id": "b" * 32})
    with pytest.raises(PdfPreparationUnavailable):
        await module.publish_pdf_binding(redis, ref)
    assert call.await_count == 2  # No setex/overwrite fallback.


@pytest.mark.asyncio
async def test_coordination_or_expiry_cannot_publish_a_false_ready_binding(monkeypatch):
    ref = {"thread_id": "thread", "expires_at": int(time.time()) - 1}
    call = AsyncMock(side_effect=RuntimeError("PRIVATE"))
    monkeypatch.setattr(module.workspace_client, "_redis_call", call)
    with pytest.raises(PdfPreparationUnavailable):
        await module.publish_pdf_binding(object(), ref)
    call.assert_not_awaited()
    ref["expires_at"] = int(time.time()) + 100
    with pytest.raises(PdfPreparationUnavailable):
        await module.publish_pdf_binding(object(), ref)
    call.assert_awaited_once()
