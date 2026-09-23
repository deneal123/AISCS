"""Тесты клиента LDR (local-deep-research) и чистых хелперов агента.

Через httpx.MockTransport — без живого сервиса (по образцу test_memos_memory.py).
"""

import httpx
import pytest

from service.domain.subagents.deep_research import DeepResearchAgent
from service.domain.subagents.research_labels import status_info
from service.infrastructure.integration.ldr_research import (
    LDRResearchClient,
    LDRResearchFailed,
    LDRUnavailableError,
)


def _client(handler, **kw):
    kw.setdefault("poll_interval", 0.0)
    kw.setdefault("timeout", 5.0)
    return LDRResearchClient(
        base_url="http://ldr.local",
        username="svc",
        password="pw",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def _handler(
    *,
    state=None,
    status_sequence=("in_progress", "completed"),
    with_metrics=True,
    sources=None,
    start_json=None,
    captured=None,
    bodies=None,
):
    state = state if state is not None else {"i": 0}

    def h(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if captured is not None:
            captured[p] = dict(request.headers)
        if bodies is not None and request.content:
            import json as _json

            try:
                bodies[p] = _json.loads(request.content)
            except Exception:
                bodies[p] = None
        if p == "/auth/login" and request.method == "GET":
            return httpx.Response(200, text='<input name="csrf_token" value="login-csrf">')
        if p == "/auth/login":
            return httpx.Response(200, json={"ok": True})
        if p == "/auth/csrf-token":
            return httpx.Response(200, json={"csrf_token": "api-csrf"})
        if p == "/api/start_research":
            return httpx.Response(200, json=start_json or {"research_id": "r1", "status": "queued"})
        if p == "/api/research/r1/status":
            i = state["i"]
            state["i"] += 1
            st = status_sequence[min(i, len(status_sequence) - 1)]
            return httpx.Response(200, json={"status": st, "progress": 50, "message": "работаю"})
        if p == "/api/report/r1":
            src = sources if sources is not None else [{"title": "A", "url": "http://a"}]
            return httpx.Response(200, json={"summary": "Итоговый отчёт", "sources": src})
        if p == "/metrics/api/metrics/research/r1":
            if not with_metrics:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "metrics": {
                        "research_id": "r1",
                        "total_tokens": 1500,
                        "total_calls": 3,
                        "model_usage": [
                            {
                                # префикс gateway → биллинг ждёт чистый id
                                "model": "openrouter:openai/gpt-4o-mini",
                                "provider": "openai_endpoint",
                                "tokens": 1500,
                                "calls": 3,
                                "prompt_tokens": 1000,
                                "completion_tokens": 500,
                            }
                        ],
                    },
                },
            )
        return httpx.Response(404)

    return h


def test_available_requires_creds():
    assert LDRResearchClient(base_url="", username="u", password="p").available is False
    assert LDRResearchClient(base_url="http://x", username="", password="p").available is False
    assert LDRResearchClient(base_url="http://x", username="u", password="p").available is True


@pytest.mark.asyncio
async def test_start_research_returns_id_sends_csrf_and_payload():
    captured: dict = {}
    bodies: dict = {}
    client = _client(_handler(captured=captured, bodies=bodies), strategy="langgraph-agent")
    rid = await client.start_research("тест")
    assert rid == "r1"
    # CSRF из /auth/csrf-token уходит в запрос на старт
    assert captured["/api/start_research"].get("x-csrftoken") == "api-csrf"
    body = bodies["/api/start_research"]
    # LDR ждёт ОДИН движок (search_engine), не список; стратегия прокинута
    assert body["search_engine"] == "searxng"
    assert body["strategy"] == "langgraph-agent"
    assert "search_engines" not in body
    await client.aclose()


@pytest.mark.asyncio
async def test_iter_status_runs_until_completed():
    client = _client(_handler(status_sequence=("in_progress", "in_progress", "completed")))
    await client.start_research("тест")
    seen = [s async for s in client.iter_status("r1")]
    assert len(seen) == 3
    assert seen[-1]["status"] == "completed"
    await client.aclose()


@pytest.mark.asyncio
async def test_iter_status_failed_raises():
    client = _client(_handler(status_sequence=("failed",)))
    await client.start_research("тест")
    with pytest.raises(LDRResearchFailed):
        _ = [s async for s in client.iter_status("r1")]
    await client.aclose()


@pytest.mark.asyncio
async def test_report_parses_summary_and_sources():
    client = _client(_handler())
    await client.start_research("тест")
    rep = await client.report("r1")
    assert rep["summary"] == "Итоговый отчёт"
    assert rep["sources"] == [{"title": "A", "url": "http://a"}]
    await client.aclose()


@pytest.mark.asyncio
async def test_metrics_parses_tokens():
    client = _client(_handler())
    await client.start_research("тест")
    m = await client.metrics("r1")
    # provider-префикс из ответа LDR снят для матчинга прайс-реестра
    assert m == {"prompt": 1000, "completion": 500, "total": 1500, "model": "openai/gpt-4o-mini"}
    await client.aclose()


@pytest.mark.asyncio
async def test_metrics_none_when_unavailable():
    client = _client(_handler(with_metrics=False))
    await client.start_research("тест")
    assert await client.metrics("r1") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_start_research_missing_id_raises():
    client = _client(_handler(start_json={"status": "queued"}))  # нет research_id
    with pytest.raises(LDRUnavailableError):
        await client.start_research("тест")
    await client.aclose()


@pytest.mark.asyncio
async def test_ensure_session_unconfigured_raises():
    client = LDRResearchClient(base_url="", username="", password="")
    with pytest.raises(LDRUnavailableError):
        await client.start_research("тест")


# --- чистые хелперы агента ------------------------------------------------- #
def test_format_sources_dict_and_str():
    out = DeepResearchAgent._format_sources(
        [{"title": "T", "url": "http://u"}, "plain source", {"name": "N"}]
    )
    assert "### Источники" in out
    assert "[T](http://u)" in out
    assert "plain source" in out
    assert "N" in out
    assert DeepResearchAgent._format_sources([]) == ""


def test_status_info_localizes_and_strips_emoji():
    # progress пробрасывается, англ. веха локализуется, эмодзи вырезаются
    progress, label = status_info({"progress": 42, "message": "🔍 3 sources gathered"})
    assert progress == 42
    assert label == "собрано источников: 3"
    assert status_info({}) == (None, "")


def test_looks_russian_detects_language():
    assert DeepResearchAgent._looks_russian("Это полностью русский отчёт о сортировках.")
    # Английский отчёт → не русский (техтермины латиницей — норма для англ.)
    assert (
        DeepResearchAgent._looks_russian(
            "Recent studies propose a new stable sorting strategy using graphs."
        )
        is False
    )
    # Русский с латинскими техтерминами и цитатами всё ещё считается русским
    assert DeepResearchAgent._looks_russian(
        "Алгоритм QuickSort и метод SPMS показали лучшую производительность [1]."
    )
    # Нечего переводить (пусто / только числа-пунктуация) → «русский», вызова не будет
    assert DeepResearchAgent._looks_russian("") is True
    assert DeepResearchAgent._looks_russian("123 [1] [2] — 456") is True


class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _FakeResp:
    def __init__(self, content, p=100, c=250):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = _FakeUsage(p, c)


@pytest.mark.asyncio
async def test_rewrite_to_russian_translates_and_bills(monkeypatch):
    from service.domain import client as client_mod
    from service.domain.run_context import require_execution

    async def fake_ccc(**kwargs):
        # англоязычный отчёт уходит пользовательским сообщением
        assert kwargs["messages"][-1]["content"] == "English report body"
        return _FakeResp("Русский отчёт", p=100, c=250)

    monkeypatch.setattr(client_mod, "create_chat_completion", fake_ccc)
    execution = require_execution()
    cursor = execution.usage.cursor()
    out = await DeepResearchAgent._rewrite_to_russian(
        "English report body", "openai/gpt-4o-mini", execution
    )
    usage = execution.usage.project_since(cursor)
    assert out == "Русский отчёт"
    assert usage["prompt"] == 100
    assert usage["completion"] == 250
    assert usage["total"] == 350
    assert usage["model"] == "openai/gpt-4o-mini"
    assert len(usage["calls"]) == 1
    assert usage["calls"][0]["kind"] == "translation"


@pytest.mark.asyncio
async def test_rewrite_to_russian_fail_open(monkeypatch):
    from service.domain import client as client_mod

    async def boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(client_mod, "create_chat_completion", boom)
    usage: dict = {}
    out = await DeepResearchAgent._rewrite_to_russian("English report", "m", usage)
    assert out == "English report"  # оригинал сохранён
    assert usage == {}  # ничего не начислено


def test_resolve_provider_normalizes(monkeypatch):
    # Overlay админки читается через снимочный прокси сайдкара, а не через admin-модуль
    # backend'а: сюда значение приезжает в теле `/run`, а не из БД.
    from service.shared import agent_settings as rs_mod

    monkeypatch.setattr(rs_mod.runtime_settings, "get_agents", lambda name, default=None: "LDR")
    assert DeepResearchAgent._resolve_provider() == "ldr"
    monkeypatch.setattr(rs_mod.runtime_settings, "get_agents", lambda name, default=None: "bogus")
    assert DeepResearchAgent._resolve_provider() == "auto"
