"""Эмбеддер-отказоустойчивость doc-vector (Фаза 2).

Смерть эмбеддер-провайдера больше не роняет vector search: фолбэк на следующего рабочего +
пересоздание коллекции при смене размерности. Чинит прод-краш (GigaChat-эмбеддер с невалидным
TLS уронил весь поиск по документам).
"""

from types import SimpleNamespace

import pytest

from service.domain.client.resilience import circuit_breaker
from service.domain.tools import vector_store


class _FakeEmbeddings:
    def __init__(self, dim, fail=False):
        self._dim = dim
        self._fail = fail

    async def create(self, model, input):  # noqa: A002 - имя параметра как у OpenAI SDK
        if self._fail:
            raise ConnectionError("embedder down")  # транспорт → circuit_breaker.should_trip=True
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self._dim) for _ in input])


class _FakeModule:
    def __init__(self, dim, fail=False):
        self.OPENAI_CLIENT = SimpleNamespace(embeddings=_FakeEmbeddings(dim, fail))


def _patch_clients(monkeypatch, modules, *, unavailable=None, active="openai"):
    # ⚠️ Патчим ФАСАД, и это не противоречит правилу «патчь там, где читают»: читает
    # здесь `vector_store`, а он берёт `get_provider_module`/`get_active_provider`
    # именно из `service.domain.client` (импорт внутри функции). Подмена в модулях
    # `chat`/`active` до него не дошла бы — проверено, тест краснел.
    import service.domain.client as client_active
    import service.domain.client as client_pkg

    monkeypatch.setattr(client_pkg, "get_provider_module", lambda name: modules.get(name))
    monkeypatch.setattr(client_active, "get_active_provider", lambda: active)

    async def _unavail(names=None):
        return set(unavailable or set())

    monkeypatch.setattr(client_pkg.provider_policy, "unavailable_providers", _unavail)


@pytest.fixture(autouse=True)
def _no_breaker_writes(monkeypatch):
    tripped = []

    async def _mark(name, **kw):
        tripped.append(name)

    async def _clear(name):
        pass

    monkeypatch.setattr(circuit_breaker, "mark_down", _mark)
    monkeypatch.setattr(circuit_breaker, "clear_down", _clear)
    return tripped


def _set_embedders(monkeypatch, primary, primary_dim, fallback):
    from service.settings import config

    monkeypatch.setattr(config.agents, "doc_embedder_model", primary)
    monkeypatch.setattr(config.agents, "doc_embedder_dim", primary_dim)
    monkeypatch.setattr(config.agents, "doc_embedder_fallback", fallback)
    # Пустой overlay: тест про фолбэк эмбеддера, а не про то, что админка его переопределит.
    from service.shared.agent_settings import runtime_settings

    monkeypatch.setattr(runtime_settings, "get_agents", lambda name, default=None: default)


@pytest.mark.asyncio
async def test_embed_falls_over_when_primary_fails(monkeypatch, _no_breaker_writes):
    # GigaChat-эмбеддер падает → гасим breaker, переходим на openrouter (dim 1536).
    _set_embedders(
        monkeypatch,
        "gigachat:Embeddings",
        1024,
        [{"model": "openrouter:openai/text-embedding-3-small", "dim": 1536}],
    )
    _patch_clients(
        monkeypatch,
        {
            "gigachat": _FakeModule(1024, fail=True),
            "openrouter": _FakeModule(1536),
        },
    )
    vectors, dim, is_primary = await vector_store._embed_with_dim(["привет"])
    assert dim == 1536
    assert len(vectors[0]) == 1536
    assert is_primary is False  # сработал фолбэк, не основной эмбеддер
    assert "gigachat" in _no_breaker_writes  # провайдер погашен


@pytest.mark.asyncio
async def test_embed_skips_unavailable_provider(monkeypatch):
    # gigachat уже заблокирован → даже не пробуем, сразу openrouter.
    _set_embedders(
        monkeypatch,
        "gigachat:Embeddings",
        1024,
        [{"model": "openrouter:openai/text-embedding-3-small", "dim": 1536}],
    )
    _patch_clients(
        monkeypatch,
        {"gigachat": _FakeModule(1024, fail=True), "openrouter": _FakeModule(1536)},
        unavailable={"gigachat"},
    )
    vectors, dim, is_primary = await vector_store._embed_with_dim(["q"])
    assert dim == 1536
    assert is_primary is False


@pytest.mark.asyncio
async def test_embed_primary_success_reports_is_primary(monkeypatch, _no_breaker_writes):
    # Основной эмбеддер жив → is_primary True (можно мигрировать коллекцию под его dim).
    _set_embedders(monkeypatch, "gigachat:Embeddings", 1024, [])
    _patch_clients(monkeypatch, {"gigachat": _FakeModule(1024)})
    _vectors, dim, is_primary = await vector_store._embed_with_dim(["q"])
    assert dim == 1024
    assert is_primary is True


@pytest.mark.asyncio
async def test_embed_raises_when_all_down(monkeypatch, _no_breaker_writes):
    _set_embedders(monkeypatch, "gigachat:Embeddings", 1024, [])
    _patch_clients(monkeypatch, {"gigachat": _FakeModule(1024, fail=True)})
    from service.domain.integration_failure import IntegrationFailure

    with pytest.raises(IntegrationFailure, match="unavailable"):
        await vector_store._embed_with_dim(["q"])


class _FakeHttp:
    def __init__(self, existing_size):
        self._size = existing_size
        self.calls = []

    async def get(self, url):
        self.calls.append(("get", url))
        if self._size is None:
            return SimpleNamespace(status_code=404, json=lambda: {})
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"result": {"config": {"params": {"vectors": {"size": self._size}}}}},
        )

    async def delete(self, url):
        self.calls.append(("delete", url))
        return SimpleNamespace(status_code=200)

    async def put(self, url, json=None, params=None, **_kw):
        self.calls.append(("put", url, (json or {}).get("vectors", {}).get("size")))
        return SimpleNamespace(status_code=200)


@pytest.mark.asyncio
async def test_ensure_collection_recreates_on_dim_change(monkeypatch):
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    http = _FakeHttp(existing_size=1024)  # была 1024
    await vector_store._ensure_collection(http, 1536)  # эмбеддер сменился на 1536
    kinds = [c[0] for c in http.calls]
    assert "delete" in kinds  # старую снесли
    assert ("put", "http://qdrant:6333/collections/gpthub_docs", 1536) in http.calls


@pytest.mark.asyncio
async def test_ensure_collection_noop_when_dim_matches(monkeypatch):
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    http = _FakeHttp(existing_size=1536)
    ready = await vector_store._ensure_collection(http, 1536)
    assert ready is True
    assert [c[0] for c in http.calls] == ["get"]  # только проверка, без пересоздания


# --------------------------------------------------------------------------- #
# P0.2 (аудит): поиск (ЧТЕНИЕ) не должен быть деструктивным                      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ensure_collection_read_path_never_deletes_on_dim_mismatch(monkeypatch):
    """Крит-находка аудита P0.2: транзиентный фейловер эмбеддера на другой dim во время
    ПОИСКА не должен сносить общий индекс всех пользователей. allow_recreate=False →
    коллекцию не трогаем, возвращаем False (поиск отдаст [])."""
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    http = _FakeHttp(existing_size=1024)  # индекс на 1024
    ready = await vector_store._ensure_collection(http, 1536, allow_recreate=False)
    assert ready is False  # не готов под новый dim
    kinds = [c[0] for c in http.calls]
    assert "delete" not in kinds, "поиск снёс общий индекс — регресс P0.2"
    assert "put" not in kinds, "поиск пересоздал коллекцию — регресс P0.2"


@pytest.mark.asyncio
async def test_ensure_collection_read_path_missing_collection_no_create(monkeypatch):
    """На пути ЧТЕНИЯ отсутствующую коллекцию не создаём — искать нечего."""
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    http = _FakeHttp(existing_size=None)  # 404 — коллекции нет
    ready = await vector_store._ensure_collection(http, 1536, allow_recreate=False)
    assert ready is False
    assert [c[0] for c in http.calls] == ["get"]  # ни delete, ни put


@pytest.mark.asyncio
async def test_search_returns_empty_without_touching_index_on_dim_mismatch(monkeypatch):
    """Сквозной путь search(): dim не совпал → [] и НИ ОДНОГО деструктивного вызова."""
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    monkeypatch.setattr(vector_store, "enabled", lambda: True)

    async def _embed(texts):
        return [[0.1] * 1536], 1536, True  # эмбеддер отдал dim 1536

    monkeypatch.setattr(vector_store, "_embed_with_dim", _embed)

    http = _FakeHttp(existing_size=1024)  # а индекс на 1024

    class _CtxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return http

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vector_store.httpx, "AsyncClient", _CtxClient)

    out = await vector_store.search(user_id="u1", query="сроки оплаты")
    assert out == []
    kinds = [c[0] for c in http.calls]
    assert "delete" not in kinds and "put" not in kinds  # индекс цел
    assert "post" not in kinds  # до самого поиска не дошли (нечего искать)


# --------------------------------------------------------------------------- #
# A1 (аудит): ИНДЕКСАЦИЯ (ЗАПИСЬ) при транзиентном фолбэке не сносит общий индекс #
# --------------------------------------------------------------------------- #
def _patch_index_http(monkeypatch, http):
    monkeypatch.setattr(vector_store, "_base", lambda: "http://qdrant:6333")
    monkeypatch.setattr(vector_store, "_collection", lambda: "gpthub_docs")
    monkeypatch.setattr(vector_store, "enabled", lambda: True)

    class _CtxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return http

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vector_store.httpx, "AsyncClient", _CtxClient)


@pytest.mark.asyncio
async def test_index_fallback_embedder_never_wipes_shared_collection(monkeypatch):
    """Крит-находка A1 (write-близнец P0.2): если во время загрузки основной эмбеддер
    мигнул и dim пришёл от ФОЛБЭКА, index_document НЕ пересоздаёт общую коллекцию —
    иначе одна загрузка стёрла бы векторы всех пользователей. Пропуск записи (→0)."""

    async def _embed(texts):
        return [[0.1] * 1536 for _ in texts], 1536, False  # фолбэк, dim 1536

    monkeypatch.setattr(vector_store, "_embed_with_dim", _embed)
    http = _FakeHttp(existing_size=1024)  # общий индекс на 1024 (основного эмбеддера)
    _patch_index_http(monkeypatch, http)

    written = await vector_store.index_document(
        user_id="u1", filename="a.txt", text="много текста " * 200
    )
    assert written == 0  # запись пропущена (fail-soft)
    kinds = [c[0] for c in http.calls]
    assert "delete" not in kinds, "фолбэк-индексация снесла общий индекс — регресс A1"
    assert "put" not in kinds, "фолбэк-индексация пересоздала/записала при mismatch — регресс A1"


@pytest.mark.asyncio
async def test_index_primary_dim_change_migrates_collection(monkeypatch):
    """Осознанная смена ОСНОВНОГО эмбеддера (is_primary) под новый dim — законная
    миграция: коллекцию пересоздаём и пишем векторы."""

    async def _embed(texts):
        return [[0.1] * 1536 for _ in texts], 1536, True  # основной, новый dim 1536

    monkeypatch.setattr(vector_store, "_embed_with_dim", _embed)
    http = _FakeHttp(existing_size=1024)  # старый индекс на 1024
    _patch_index_http(monkeypatch, http)

    written = await vector_store.index_document(
        user_id="u1", filename="a.txt", text="много текста " * 200
    )
    assert written > 0
    kinds = [c[0] for c in http.calls]
    assert "delete" in kinds  # старую снесли (миграция под основной эмбеддер)
    assert (
        "put",
        "http://qdrant:6333/collections/gpthub_docs",
        1536,
    ) in http.calls  # создали под 1536
