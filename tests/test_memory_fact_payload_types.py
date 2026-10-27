"""Malformed extraction fields must never become durable string representations."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.analytics.application.memory.service import MemoryService


@pytest.mark.parametrize("field", ["value", "key", "type"])
@pytest.mark.parametrize("invalid", [{"name": "Алина"}, ["Алина"], 28, True])
def test_non_text_fact_fields_are_rejected(field, invalid):
    item = {"type": "identity", "key": "имя", "value": "Пользователя зовут Данил"}
    item[field] = invalid
    assert MemoryService._parse_facts(json.dumps({"facts": [item]})) == []


def test_invalid_item_does_not_discard_valid_neighbour():
    raw = json.dumps(
        {
            "facts": [
                {"type": "identity", "key": "имя", "value": {"name": "Алина"}},
                {"type": "identity", "key": "имя", "value": "Пользователя зовут Данил"},
            ]
        }
    )
    assert MemoryService._parse_facts(raw) == [
        {"type": "identity", "key": "имя", "value": "Пользователя зовут Данил"},
    ]


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_optional_key_uses_valid_text_value(key):
    raw = json.dumps({"facts": [{"key": key, "value": "Пользователь предпочитает Python"}]})
    assert MemoryService._parse_facts(raw) == [
        {
            "type": "general",
            "key": "Пользователь предпочитает Python",
            "value": "Пользователь предпочитает Python",
        }
    ]


@pytest.mark.asyncio
async def test_rejected_fact_is_not_persisted_but_accepted_usage_is_preserved(monkeypatch):
    completion = AsyncMock(
        return_value=(
            json.dumps({"facts": [{"key": "имя", "value": {"name": "Алина"}}]}),
            {
                "calls": [
                    {
                        "receipt_id": "synthetic-memory-call",
                        "provider": "gigachat",
                        "model": "GigaChat-2",
                        "prompt": 12,
                        "completion": 5,
                    }
                ]
            },
        )
    )
    monkeypatch.setattr("service.infrastructure.llm_gateway.chat_completion", completion)
    repo = SimpleNamespace(upsert_fact=AsyncMock())
    service = MemoryService(integration=SimpleNamespace(), facts_repo=repo)
    usage = {}
    await service.extract_and_save_facts(
        user_id="synthetic-user",
        thread_id="synthetic-thread",
        messages=[{"role": "user", "content": "ты Алина, не я"}],
        usage_out=usage,
    )
    completion.assert_awaited_once()
    repo.upsert_fact.assert_not_awaited()
    assert usage["total"] == 17
    assert len(usage["calls"]) == 1
    assert usage["calls"][0]["receipt_id"] == "synthetic-memory-call"
