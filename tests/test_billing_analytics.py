"""Фаза 6 биллинга (бэкенд): аналитика использования для графиков UI."""

from datetime import date

import pytest

from service.services.billing.application.billing_service import BillingService, shape_analytics
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


def test_shape_analytics_aggregates() -> None:
    daily = [
        {"day": date(2026, 6, 1), "requests": 2, "credits": 100, "tokens": 500},
        {"day": date(2026, 6, 2), "requests": 1, "credits": 50, "tokens": 200},
    ]
    events = [
        {"tokens": 300, "metadata": {"credits": 80, "model": "gpt", "tools": ["deep_research"]}},
        {"tokens": 200, "metadata": {"credits": 70, "model": "gpt", "tools": []}},
    ]
    out = shape_analytics(daily, events)

    # tokens теперь есть в каждой строке series
    assert out["series"][0] == {"day": "2026-06-01", "credits": 100, "requests": 2, "tokens": 500}
    # by_model[0] обогащён token-полями (старые события без prompt/completion → 0)
    model = out["by_model"][0]
    assert model["name"] == "gpt"
    assert model["credits"] == 150
    assert model["tokens"] == 500  # сумма верхнеуровневых tokens событий
    assert model["prompt_tokens"] == 0
    assert model["completion_tokens"] == 0
    assert model["requests"] == 2
    by_agent = {item["name"]: item["credits"] for item in out["by_agent"]}
    assert by_agent == {"deep_research": 80, "general": 70}
    assert out["totals"]["credits"] == 150
    assert out["totals"]["requests"] == 3
    assert out["totals"]["avg_credits_per_request"] == 50.0
    assert out["totals"]["peak_day"] == "2026-06-01"


def test_shape_analytics_prompt_completion_split_and_top_requests() -> None:
    daily = [{"day": date(2026, 6, 1), "requests": 3, "credits": 300, "tokens": 1200}]
    events = [
        {
            "tokens": 600,
            "metadata": {
                "credits": 200,
                "model": "gpt",
                "prompt": 400,
                "completion": 200,
                "thread_id": "t-expensive",
                "tools": ["deep_research"],
            },
        },
        {
            "tokens": 300,
            "metadata": {
                "credits": 60,
                "model": "gpt",
                "prompt": 250,
                "completion": 50,
                "thread_id": "t-mid",
            },
        },
        # старое событие без prompt/completion — деградирует к 0, но копит tokens
        {"tokens": 300, "metadata": {"credits": 40, "model": "qwen", "thread_id": "t-old"}},
    ]
    out = shape_analytics(daily, events)

    gpt = next(item for item in out["by_model"] if item["name"] == "gpt")
    assert gpt["prompt_tokens"] == 650
    assert gpt["completion_tokens"] == 250
    assert gpt["tokens"] == 900
    assert gpt["credits"] == 260
    assert gpt["requests"] == 2
    qwen = next(item for item in out["by_model"] if item["name"] == "qwen")
    assert qwen["prompt_tokens"] == 0
    assert qwen["completion_tokens"] == 0
    assert qwen["tokens"] == 300

    # top_requests отсортированы по credits (desc), несут расщепление токенов и thread_id
    top = out["top_requests"]
    assert [r["credits"] for r in top] == [200, 60, 40]
    assert top[0] == {
        "model": "gpt",
        "credits": 200,
        "prompt_tokens": 400,
        "completion_tokens": 200,
        "tokens": 600,
        "thread_id": "t-expensive",
    }


def test_shape_analytics_empty() -> None:
    out = shape_analytics([], [])
    assert out["series"] == []
    assert out["by_model"] == []
    assert out["top_requests"] == []
    assert out["totals"] == {
        "credits": 0,
        "requests": 0,
        "avg_credits_per_request": 0.0,
        "peak_day": None,
    }


class _FakeAnalyticsRepo:
    async def fetch_usage_daily(self, *, user_id, since):
        return [{"day": date(2026, 6, 1), "requests": 2, "credits": 100, "tokens": 500}]

    async def fetch_usage_events(self, *, user_id, since):
        return [{"tokens": 300, "metadata": {"credits": 100, "model": "gpt", "tools": []}}]


@pytest.mark.asyncio
async def test_service_get_usage_analytics() -> None:
    from types import SimpleNamespace

    svc = BillingService(_FakeAnalyticsRepo(), SimpleNamespace())
    out = await svc.get_usage_analytics("u1", range_key="7d", today=date(2026, 6, 26))
    assert out["range"] == "7d"
    assert out["totals"]["credits"] == 100
    # getattr-guard: у SimpleNamespace нет credit_unit_rub → None (не падаем)
    assert out["totals"]["credit_unit_rub"] is None
    assert out["by_model"][0]["name"] == "gpt"


@pytest.mark.asyncio
async def test_repo_fetch_usage_daily_and_events() -> None:
    session = FakeDBSession(
        all_map={
            "FROM profile.usage_daily": [(date(2026, 6, 1), 2, 100, 500)],
            "FROM profile.billing_events": [
                (300, {"credits": 80, "model": "gpt"}),
                (200, '{"credits": 70, "model": "qwen"}'),  # JSONB как строка
            ],
        }
    )
    repo = BillingRepository(FakeConnector(session))
    daily = await repo.fetch_usage_daily(user_id="u1", since=date(2026, 6, 1))
    events = await repo.fetch_usage_events(user_id="u1", since=date(2026, 6, 1))

    assert daily == [{"day": date(2026, 6, 1), "requests": 2, "credits": 100, "tokens": 500}]
    assert events[0]["metadata"]["model"] == "gpt"
    assert events[1]["metadata"]["credits"] == 70  # распарсилось из строки
