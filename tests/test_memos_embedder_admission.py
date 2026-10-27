"""Unavailable embedder settings must never turn into a successful destructive change."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from service.infrastructure import provider_policy_store
from service.infrastructure.memory import memos
from service.services.admin.application import admin_service
from service.services.admin.application.admin_service import AdminService
from service.services.admin.application.settings.registry import REGISTRY
from service.services.admin.presentation.routers import admin_api
from service.services.admin.presentation.routers.admin_api import (
    MemosEmbedderRequest,
    set_memos_embedder,
)


def setup_missing_pair(monkeypatch):
    for key in ("agents.memos_embedder_model", "agents.memos_embedder_dim"):
        monkeypatch.delitem(REGISTRY, key, raising=False)
    repository = Mock(upsert=AsyncMock())
    service = AdminService(Mock(), repository)
    wipe = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(admin_api, "wipe_memos_memory", wipe)
    monkeypatch.setattr(memos, "wipe_memos_memory", wipe)
    return service, repository, wipe


@pytest.mark.asyncio
async def test_manual_change_without_registered_pair_never_writes_or_wipes(monkeypatch):
    service, repository, wipe = setup_missing_pair(monkeypatch)
    with pytest.raises(HTTPException) as error:
        await set_memos_embedder(
            MemosEmbedderRequest(model="gigachat:Embeddings", dimension=1024),
            SimpleNamespace(user_id="fixture-admin"),
            service,
        )
    assert error.value.status_code == 422
    repository.upsert.assert_not_awaited()
    wipe.assert_not_awaited()


@pytest.mark.asyncio
async def test_cascade_uses_keyword_setting_contract_and_stops_on_missing_admission(monkeypatch):
    service, repository, wipe = setup_missing_pair(monkeypatch)
    monkeypatch.setattr(
        admin_service.runtime_settings,
        "get_agents",
        lambda key, default: (
            "gigachat:Embeddings"
            if key == "memos_embedder_model"
            else [{"model": "fixture:model", "dim": 1024}]
        ),
    )
    monkeypatch.setattr(provider_policy_store, "blocked_providers", AsyncMock(return_value=set()))
    monkeypatch.setattr(provider_policy_store, "disabled_providers", lambda: set())
    real_setting = AsyncMock(wraps=service.set_setting)
    monkeypatch.setattr(service, "set_setting", real_setting)
    await service._cascade_memos_embedder({"gigachat"})
    real_setting.assert_awaited_once_with(
        key="agents.memos_embedder_model", value="fixture:model", updated_by="cascade"
    )
    repository.upsert.assert_not_awaited()
    wipe.assert_not_awaited()
