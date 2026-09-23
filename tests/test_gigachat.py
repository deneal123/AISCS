"""Тесты GigaChat-провайдера: OAuth-токен, auth-flow, клиент (Фаза 0)."""

import ssl
import time
import types

import certifi
import httpx
import pytest

from service.domain.client.providers import gigachat, gigachat_auth


def _make_manager(monkeypatch, *, tokens=("tok-1", "tok-2", "tok-3"), expires_ahead_sec=3600):
    """Менеджер токенов с замоканным OAuth-эндпоинтом, считающим обращения."""
    state = {"calls": 0}
    seq = list(tokens)

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.headers.get("RqUID")
        idx = min(state["calls"], len(seq) - 1)
        token = seq[idx]
        state["calls"] += 1
        expires_at_ms = int((time.time() + expires_ahead_sec) * 1000)
        return httpx.Response(200, json={"access_token": token, "expires_at": expires_at_ms})

    _real_async_client = httpx.AsyncClient

    def _factory(**_kwargs):
        return _real_async_client(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(gigachat_auth.httpx, "AsyncClient", _factory)
    manager = gigachat_auth.GigaChatTokenManager(
        authorization_key="dGVzdDp0ZXN0",  # base64("test:test")
        scope="GIGACHAT_API_PERS",
        oauth_url="https://oauth.local/oauth",
        verify=False,
        timeout=5.0,
        skew_sec=60,
    )
    return manager, state


@pytest.mark.asyncio
async def test_token_manager_caches_until_expiry(monkeypatch):
    manager, state = _make_manager(monkeypatch)
    t1 = await manager.get_token()
    t2 = await manager.get_token()
    assert t1 == "tok-1"
    assert t2 == "tok-1"
    assert state["calls"] == 1  # второй вызов — из кэша


@pytest.mark.asyncio
async def test_token_manager_refreshes_after_invalidate(monkeypatch):
    manager, state = _make_manager(monkeypatch)
    assert await manager.get_token() == "tok-1"
    manager.invalidate()
    assert await manager.get_token() == "tok-2"
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_token_manager_refreshes_when_near_expiry(monkeypatch):
    # expires_ahead < skew → токен сразу считается несвежим, рефреш на каждый вызов
    manager, state = _make_manager(monkeypatch, expires_ahead_sec=10)
    await manager.get_token()
    await manager.get_token()
    assert state["calls"] == 2


def test_token_manager_lock_survives_new_event_loop(monkeypatch):
    """Регрессия P1.1: celery крутит НОВЫЙ event loop на каждую задачу, а менеджер —
    модульный синглтон. Лок, созданный в __init__, привязался бы к первому loop, и
    второй запрос воркера падал бы `RuntimeError: bound to a different event loop`.
    Ленивая пере-привязка лока к текущему loop это чинит.
    """
    import asyncio

    manager, state = _make_manager(monkeypatch)

    # Первая celery-задача — свой loop; берёт токен под локом.
    t1 = asyncio.run(manager.get_token())
    # Вторая задача — ДРУГОЙ loop. invalidate форсирует рефреш → снова захват лока.
    # Без пере-привязки здесь RuntimeError (лок от первого, уже закрытого loop).
    manager.invalidate()
    t2 = asyncio.run(manager.get_token())

    assert t1 == "tok-1"
    assert t2 == "tok-2"
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_token_manager_requires_key(monkeypatch):
    manager = gigachat_auth.GigaChatTokenManager(
        authorization_key="",
        scope="GIGACHAT_API_PERS",
        oauth_url="https://oauth.local/oauth",
        verify=False,
        timeout=5.0,
    )
    with pytest.raises(RuntimeError):
        await manager.get_token()


def test_gigachat_tls_builds_context_from_explicit_bundle(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "gigachat_ca_bundle", certifi.where())
    monkeypatch.setattr(config.agents, "gigachat_verify_ssl", True)

    assert isinstance(gigachat._build_verify(), ssl.SSLContext)
    assert gigachat.configuration_error() is None


def test_gigachat_tls_rejects_missing_or_invalid_bundle_with_bounded_code(monkeypatch, tmp_path):
    from service.settings import config

    monkeypatch.setattr(config.agents, "gigachat_verify_ssl", True)
    for value in ("", str(tmp_path / "missing-private-path.pem")):
        monkeypatch.setattr(config.agents, "gigachat_ca_bundle", value)
        with pytest.raises(gigachat.GigaChatTLSConfigError) as caught:
            gigachat._build_verify()
        assert str(caught.value) == "tls_config"
        assert "missing-private-path" not in str(caught.value)
        assert gigachat.configuration_error() == "tls_config"


def test_gigachat_tls_rejects_expired_bundle_with_bounded_code(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "gigachat_ca_bundle", certifi.where())
    monkeypatch.setattr(config.agents, "gigachat_verify_ssl", True)
    monkeypatch.setattr(
        ssl._ssl,  # type: ignore[attr-defined]  # noqa: SLF001
        "_test_decode_cert",
        lambda _path: {
            "notBefore": "Jan  1 00:00:00 2000 GMT",
            "notAfter": "Jan  1 00:00:00 2001 GMT",
        },
    )

    with pytest.raises(gigachat.GigaChatTLSConfigError, match="tls_config"):
        gigachat._build_verify()
    assert gigachat.configuration_error() == "tls_config"


def test_gigachat_tls_can_be_disabled_only_explicitly(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "gigachat_ca_bundle", "")
    monkeypatch.setattr(config.agents, "gigachat_verify_ssl", False)

    assert gigachat._build_verify() is False


@pytest.mark.asyncio
async def test_auth_flow_injects_bearer_and_retries_on_401(monkeypatch):
    manager, state = _make_manager(monkeypatch)
    auth = gigachat_auth.GigaChatAuth(manager)

    request = httpx.Request("POST", "https://gigachat.local/api/v1/chat/completions")
    flow = auth.async_auth_flow(request)

    req1 = await flow.asend(None)
    assert req1.headers["Authorization"] == "Bearer tok-1"

    # Сервер ответил 401 → ожидаем повтор со свежим токеном.
    req2 = await flow.asend(httpx.Response(401))
    assert req2.headers["Authorization"] == "Bearer tok-2"

    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200))


# --------------------------------------------------------------------------- #
# gigachat_client helpers                                                       #
# --------------------------------------------------------------------------- #
class _FakeModel:
    def __init__(self, mid):
        self.id = mid


class _FakeModelsAPI:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    async def list(self):
        self.calls += 1
        return types.SimpleNamespace(data=self._data)


class _FakeChatAPI:
    def __init__(self):
        self.last_payload = None

    async def create(self, **payload):
        self.last_payload = payload
        return types.SimpleNamespace(choices=[])


class _FakeClient:
    def __init__(self, data):
        self.models = _FakeModelsAPI(data)
        self.chat = types.SimpleNamespace(completions=_FakeChatAPI())


@pytest.mark.asyncio
async def test_gigachat_list_models_cached(monkeypatch):
    gigachat.clear_models_cache()
    fake = _FakeClient([_FakeModel("GigaChat-2"), _FakeModel("GigaChat-2-Pro"), _FakeModel("")])
    first = await gigachat.list_available_models(client=fake, force_refresh=True)
    second = await gigachat.list_available_models(client=fake)
    assert first == ["GigaChat-2", "GigaChat-2-Pro"]
    assert second == first
    assert fake.models.calls == 1


@pytest.mark.asyncio
async def test_gigachat_create_completion_bridges_to_chat():
    fake = _FakeClient([])
    await gigachat.create_completion("привет", "GigaChat", client=fake)
    payload = fake.chat.completions.last_payload
    assert payload["messages"] == [{"role": "user", "content": "привет"}]
    assert payload["model"] == "GigaChat"


# --------------------------------------------------------------------------- #
# B8 (аудит): диалект function-calling на НЕ-стрим пути                          #
# --------------------------------------------------------------------------- #
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_graph",
            "description": "Поиск",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string", "description": "Запрос"}},
            },
        },
    }
]


@pytest.mark.asyncio
async def test_gigachat_translates_tools_to_functions_on_non_stream():
    """tools GigaChat молча игнорит — на не-стрим пути раньше их не переводили (B8)."""
    fake = _FakeClient([])
    await gigachat.create_chat_completion(
        [{"role": "user", "content": "что я загружал?"}],
        "GigaChat",
        client=fake,
        tools=TOOLS,
        tool_choice="auto",
    )
    payload = fake.chat.completions.last_payload
    assert payload["functions"][0]["name"] == TOOLS[0]["function"]["name"]
    assert payload["functions"][0]["parameters"]["properties"]["q"]["description"] == "Запрос"
    assert payload["function_call"] == "auto"
    assert "tools" not in payload and "tool_choice" not in payload


@pytest.mark.asyncio
async def test_gigachat_translates_tool_history_even_without_tools():
    """Каноническая tool-история (role=tool) БЕЗ tools в вызове роняла 422 — переводим."""
    fake = _FakeClient([])
    messages = [
        {"role": "user", "content": "?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "результат"},
    ]
    await gigachat.create_chat_completion(messages, "GigaChat", client=fake)
    sent = fake.chat.completions.last_payload["messages"]
    # assistant.tool_calls → function_call; role=tool → role=function (иначе 422)
    assert "tool_calls" not in sent[1] and sent[1]["function_call"]["name"] == "f"
    assert sent[2]["role"] == "function"


class _RespChatAPI:
    """Возвращает заданный SDK-подобный ответ (с model_dump/model_validate)."""

    def __init__(self, response):
        self._response = response
        self.last_payload = None

    async def create(self, **payload):
        self.last_payload = payload
        return self._response


class _FakeSDKResponse:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data

    @classmethod
    def model_validate(cls, data):
        return cls(data)


@pytest.mark.asyncio
async def test_gigachat_canonicalizes_function_call_response():
    """Ответ GigaChat (function_call) → канон (tool_calls), чтобы шлюз/LDR его увидели."""
    resp = _FakeSDKResponse(
        {
            "choices": [
                {
                    "finish_reason": "function_call",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {"name": "f", "arguments": {"q": "k8s"}},
                    },
                }
            ]
        }
    )
    fake = _FakeClient([])
    fake.chat = types.SimpleNamespace(completions=_RespChatAPI(resp))
    out = await gigachat.create_chat_completion(
        [{"role": "user", "content": "?"}], "GigaChat", client=fake, tools=TOOLS
    )
    choice = out.model_dump()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "f"


@pytest.mark.parametrize(
    ("configured", "expected", "why"),
    [
        (
            "https://api.giga.chat/v1/",
            "https://api.giga.chat/v1",
            "хвостовой слэш срезается",
        ),
        (
            "https://api.giga.chat/v1",
            "https://api.giga.chat/v1",
            "⚠️ /v1 НЕ задваивается: актуальная база уже оканчивается на /v1",
        ),
        ("", "https://api.giga.chat/v1", "пусто → дефолт провайдера"),
    ],
)
def test_gigachat_base_url_keeps_v1(monkeypatch, configured, expected, why):
    """База GigaChat не получает лишнего суффикса.

    ⚠️ Проверяется РЕЗУЛЬТАТ через спеку, а не приватный `_resolve_gigachat_base_url`:
    обвязка переехала в общую фабрику, и тест, привязанный к имени хелпера, ловил бы
    переезд, а не поведение. Само свойство — `base_url_suffix=None` в спеке.
    """
    from service.domain.client.providers.runtime import ProviderRuntime
    from service.settings import config

    monkeypatch.setattr(config.agents, "gigachat_base_url", configured)

    assert ProviderRuntime(gigachat.SPEC).resolve_base_url() == expected, why
