"""Тесты MemOS-интеграции памяти (адаптер + выбор провайдера)."""

import json

import httpx
import pytest

from service.infrastructure import memory as integ_pkg
from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.settings import config


def _adapter(handler, **kw):
    return MemOSMemoryIntegration(
        base_url="http://memos.local",
        transport=httpx.MockTransport(handler),
        mem_cube_template="gpthub-{user_id}",
        **kw,
    )


def _capturing_handler(captured, *, search_payload=None, status=200):
    def _h(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        captured[request.url.path] = {"body": body, "headers": dict(request.headers)}
        if status >= 400:
            return httpx.Response(status)
        if request.url.path == "/product/search":
            return httpx.Response(200, json=search_payload or {"data": []})
        return httpx.Response(200, json={"status": "ok"})

    return _h


# --------------------------------------------------------------------------- #
# available                                                                     #
# --------------------------------------------------------------------------- #
def test_available_requires_base_url():
    assert MemOSMemoryIntegration(base_url="").available is False
    assert MemOSMemoryIntegration(base_url="http://x").available is True


# --------------------------------------------------------------------------- #
# get_memory_context                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_memory_context_formats_and_scopes_cube():
    captured = {}
    payload = {"data": [{"memory": "любит клубнику"}, {"text": "работает в IT"}, {"noise": 1}]}
    adapter = _adapter(_capturing_handler(captured, search_payload=payload))

    ctx = await adapter.get_memory_context(user_id="42", top_k=5)

    assert ctx.startswith("## Контекст из памяти пользователя:")
    assert "- любит клубнику" in ctx
    assert "- работает в IT" in ctx
    req = captured["/product/search"]["body"]
    assert req["user_id"] == "42"
    assert req["mem_cube_id"] == "gpthub-42"  # изоляция по пользователю
    assert req["top_k"] == 5


@pytest.mark.asyncio
async def test_get_memory_context_empty_when_no_items():
    adapter = _adapter(_capturing_handler({}, search_payload={"data": []}))
    assert await adapter.get_memory_context(user_id="1") == ""


@pytest.mark.asyncio
async def test_get_memory_context_failopen_on_http_error():
    adapter = _adapter(_capturing_handler({}, status=500))
    assert await adapter.get_memory_context(user_id="1") == ""


@pytest.mark.asyncio
async def test_get_memory_context_failopen_on_network_error():
    def _boom(request):
        raise httpx.ConnectError("down")

    adapter = _adapter(_boom)
    assert await adapter.get_memory_context(user_id="1") == ""


# --------------------------------------------------------------------------- #
# save_messages                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_save_messages_posts_add_with_cube_and_mode():
    captured = {}
    adapter = _adapter(_capturing_handler(captured), api_key="secret")

    await adapter.save_messages(
        user_id="42",
        messages=[{"role": "user", "content": "привет"}, {"role": "assistant", "content": ""}],
        metadata={"thread_id": "t1"},
    )

    add = captured["/product/add"]
    body = add["body"]
    assert body["user_id"] == "42"
    assert body["mem_cube_id"] == "gpthub-42"
    assert body["messages"] == [{"role": "user", "content": "привет"}]  # пустое отброшено
    assert body["async_mode"] == "sync"
    assert body["metadata"] == {"thread_id": "t1"}
    assert add["headers"].get("authorization") == "Bearer secret"


@pytest.mark.asyncio
async def test_save_messages_noop_when_unavailable():
    captured = {}
    adapter = MemOSMemoryIntegration(
        base_url="", transport=httpx.MockTransport(_capturing_handler(captured))
    )
    await adapter.save_messages(user_id="1", messages=[{"role": "user", "content": "x"}])
    assert captured == {}  # запроса не было


# --------------------------------------------------------------------------- #
# factory provider selection                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_singleton():
    integ_pkg.reset_memory_integration_singleton()
    yield
    integ_pkg.reset_memory_integration_singleton()


def test_factory_selects_memos(monkeypatch):
    monkeypatch.setattr(config.agents, "memory_provider", "memos")
    monkeypatch.setattr(config.agents, "memos_base_url", "http://memos.local")
    integ = integ_pkg.get_memory_integration()
    assert integ.name == "memos"
    assert integ.available is True


def test_factory_noop_when_memos_unconfigured(monkeypatch):
    monkeypatch.setattr(config.agents, "memory_provider", "memos")
    monkeypatch.setattr(config.agents, "memos_base_url", "")
    integ = integ_pkg.get_memory_integration()
    assert integ.available is False


def test_factory_explicit_noop(monkeypatch):
    monkeypatch.setattr(config.agents, "memory_provider", "noop")
    assert integ_pkg.get_memory_integration().available is False


# --------------------------------------------------------------------------- #
# wipe — «очистить» в админке                                                   #
# --------------------------------------------------------------------------- #
# ⚠️ Этот вызов жил В ДВУХ КОПИЯХ (`admin_service` и `admin_api`), обе на голом httpx
# мимо клиента MemOS и обе БЕЗ заголовка авторизации. Пока `AGENTS__MEMOS_API_KEY` пуст,
# разницы не видно; в день, когда его зададут, сброс памяти начал бы получать 401, а
# остальная интеграция продолжила бы работать — кнопка «очистить» молча перестала бы
# очищать. Тестов у копий не было ни одного.
@pytest.mark.asyncio
async def test_wipe_posts_admin_endpoint_with_auth():
    captured = {}
    adapter = _adapter(_capturing_handler(captured), api_key="memos-key")

    result = await adapter.wipe()

    assert result["ok"] is True
    assert "/product/admin/wipe" in captured
    assert captured["/product/admin/wipe"]["headers"]["authorization"] == "Bearer memos-key"


@pytest.mark.asyncio
async def test_wipe_reports_failure_instead_of_silent_ok():
    """⚠️ «Стёрли» и «не смогли стереть» путать нельзя.

    Администратор нажал «очистить»; рапорт об успехе при оставшихся в Qdrant текстах
    пользователя — прямой обман. Поэтому ответ явный, а не fail-open `None`, как у
    обычного `_post`.
    """
    adapter = _adapter(_capturing_handler({}, status=500))

    assert (await adapter.wipe())["ok"] is False


@pytest.mark.asyncio
async def test_wipe_reports_failure_on_network_error():
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("memos лежит")

    assert (await _adapter(_boom).wipe())["ok"] is False


@pytest.mark.asyncio
async def test_wipe_without_base_url_is_not_ok():
    """Адрес не задан — это НЕ «успешно стёрли»."""
    result = await MemOSMemoryIntegration(base_url="").wipe()

    assert result["ok"] is False
    assert result["reason"] == "no_memos_base_url"
