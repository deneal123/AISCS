"""Векторное хранилище через сайдкар (Фаза 3): индексация, поиск, снос.

Хранилище считает эмбеддинги мультипровайдерным слоем, которым владеет сайдкар, — туда
и переехали операции; backend (upload, graph_api) стал клиентом. Фолбэк на локальный
вызов безопасен ровно потому, что Qdrant у обеих сторон ОДИН.

Самое важное здесь — различать «сходили и сносить было нечего» (``False``) и «не сходили
вовсе» (``None``). Спутать их значит оставить тексты пользователя в Qdrant после того,
как он нажал «очистить», и отрапортовать об успехе.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from service.infrastructure.agents_client import sidecar_vector


def _cfg(url: str = "http://agents:8090"):
    return SimpleNamespace(
        agents=SimpleNamespace(sidecar_url=url, llm_gateway_api_key="gateway-key")
    )


class _Resp:
    """Совместимость с прежними вызовами `_patch(resp=_Resp(...))`."""

    def __init__(self, status: int, payload=None):
        self.status_code = status
        self.payload = payload if payload is not None else {}


def _patch(monkeypatch, *, resp=None, boom=None):
    """Подменяет ТРАНСПОРТ клиента, а не сам клиент.

    ⚠️ Раньше тест патчил `sidecar_vector.httpx.AsyncClient` — то есть знал, что модуль
    ходит в сеть напрямую. После перехода на общую базу такого атрибута нет, и подмена
    молча перестала бы что-либо значить. Через `httpx.MockTransport` проверяется РАБОЧИЙ
    путь клиента целиком: заголовки, разбор ошибки, классификация.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["json"] = json.loads(request.content.decode("utf-8")) if request.content else None
        if boom is not None:
            raise httpx.ConnectError(str(boom))
        return httpx.Response(resp.status_code, json=resp.payload)

    transport = httpx.MockTransport(_handler)
    original = sidecar_vector._client

    def _factory(config, timeout):
        client = original(config, timeout)
        client._transport = transport
        return client

    monkeypatch.setattr(sidecar_vector, "_client", _factory)
    return seen


@pytest.mark.asyncio
async def test_index_posts_document_with_auth(monkeypatch) -> None:
    seen = _patch(monkeypatch, resp=_Resp(200, {"chunks": 12}))

    chunks = await sidecar_vector.index_document(_cfg(), user_id="7", filename="a.pdf", text="т")

    assert chunks == 12
    assert seen["url"] == "http://agents:8090/vector/index"
    assert seen["json"] == {"user_id": "7", "filename": "a.pdf", "text": "т"}
    # ⚠️ Ключ ASCII: заголовки HTTP кодируются latin-1, и кириллица здесь роняет
    # запрос на уровне httpx. Прежний фейковый клиент этого не показывал — он
    # заголовки не кодировал вовсе.
    assert seen["headers"]["authorization"] == "Bearer gateway-key"


@pytest.mark.asyncio
async def test_search_returns_passages(monkeypatch) -> None:
    _patch(monkeypatch, resp=_Resp(200, {"passages": [{"text": "фрагмент"}]}))
    got = await sidecar_vector.search(_cfg(), user_id="7", query="что", top_k=3)
    assert got == [{"text": "фрагмент"}]


@pytest.mark.asyncio
async def test_delete_distinguishes_nothing_to_delete_from_not_asked(monkeypatch) -> None:
    """False = сходили, сносить было нечего. None = не сходили. Путать нельзя."""
    _patch(monkeypatch, resp=_Resp(200, {"deleted": False}))
    assert await sidecar_vector.delete_user_documents(_cfg(), user_id="7") is False

    _patch(monkeypatch, boom=RuntimeError("сеть легла"))
    assert await sidecar_vector.delete_user_documents(_cfg(), user_id="7") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs", [{"boom": RuntimeError("нет связи")}, {"resp": _Resp(503)}, {"resp": _Resp(200, [])}]
)
async def test_transport_failures_return_none(monkeypatch, kwargs) -> None:
    _patch(monkeypatch, **kwargs)
    assert await sidecar_vector.search(_cfg(), user_id="7", query="q") is None


@pytest.mark.asyncio
async def test_index_is_best_effort_when_sidecar_silent(monkeypatch) -> None:
    """Индексация всегда была best-effort: её сбой не должен ронять загрузку файла —
    пользователь потерял бы документ из-за неработающего поиска."""
    monkeypatch.setattr(sidecar_vector, "index_document", _async(None))
    got = await sidecar_vector.index_document_best_effort(
        _cfg(), user_id="7", filename="a.pdf", text="т"
    )
    assert got == 0


@pytest.mark.asyncio
async def test_search_degrades_to_empty(monkeypatch) -> None:
    """Отсутствие контекста — не ошибка: ассистент отвечает без него (так вело себя и
    локальное хранилище)."""
    monkeypatch.setattr(sidecar_vector, "search", _async(None))
    assert await sidecar_vector.search_best_effort(_cfg(), user_id="7", query="q") == []


@pytest.mark.asyncio
async def test_delete_reports_failure_instead_of_pretending(monkeypatch) -> None:
    """Здесь fail-open НЕДОПУСТИМ: сказать «удалено», не удалив, — прямой обман.

    Разница с поиском принципиальная: пустой поиск пользователь переживёт, а «очистил
    базу знаний», после которого тексты остались в Qdrant, — нет.
    """
    monkeypatch.setattr(sidecar_vector, "delete_user_documents", _async(None))
    assert await sidecar_vector.delete_user_documents_strict(_cfg(), user_id="7") is False


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
