"""Offline behavior contracts at the extracted backend ownership boundaries."""

import asyncio

import pytest

from service.configuration.agents import AgentsConfig
from service.services.chat.infrastructure.agent_context import PseudoSession, create_session
from service.services.chat.infrastructure.history_session import PseudoSession as HistorySession
from service.settings import AgentsConfig as PublicAgentsConfig


def test_agent_settings_keep_public_import_and_environment_contract(monkeypatch):
    assert PublicAgentsConfig is AgentsConfig
    monkeypatch.setenv("AGENTS__LLM_PROVIDER", " RouterAI ")
    monkeypatch.setenv("AGENTS__PROXY_PORT", "")
    monkeypatch.setenv("AGENTS__GIGACHAT_SCOPE", "gigachat_api_corp")
    monkeypatch.setenv("AGENTS__CHAT_HISTORY_MESSAGES_LIMIT", "-2")
    settings = AgentsConfig(_env_file=None)
    assert settings.llm_provider == "routerai"
    assert settings.proxy_port is None
    assert settings.gigachat_scope == "GIGACHAT_API_CORP"
    assert settings.chat_history_messages_limit == 0
    assert settings.model_config["env_prefix"] == "AGENTS__"


@pytest.mark.asyncio
async def test_history_session_keeps_copy_limit_and_clear_semantics():
    assert PseudoSession is HistorySession
    assert isinstance(create_session("thread"), HistorySession)
    session = HistorySession("thread", max_items=3)
    await asyncio.gather(*(session.add_items([{"i": i}]) for i in range(10)))
    items = await session.get_items()
    assert len(items) == 3
    items.clear()
    assert len(await session.get_items()) == 3
    latest = await session.get_items(limit=1)
    assert await session.pop_item() == latest[0]
    await session.clear_session()
    assert await session.get_items() == []
    assert await session.pop_item() is None


@pytest.mark.asyncio
async def test_history_session_expiry_does_not_discard_live_items():
    session = HistorySession("thread", ttl_seconds=60)
    await session.add_items([{"ts": 0, "value": "expired"}, {"value": "live"}])
    assert await session.get_items() == [{"value": "live"}]
