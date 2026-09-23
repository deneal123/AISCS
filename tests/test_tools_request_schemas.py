"""`/tools/*` описаны схемой, а не разбираются вручную из `dict`.

⚠️ ЧТО БЫЛО. Три ручки принимали `payload: dict` и доставали поля через `.get()`.
Каждое следствие молчаливое, и ни одно не выглядело ошибкой вызывающего:

* забыл `query` → `.get("query", "")` → `""` → ответ `{"results": []}` с кодом 200.
  «Ничего не нашлось» и «я не передал запрос» отдавались ОДИНАКОВО;
* прислал `{"num_results": "много"}` → строка доезжала до `int()` → 500. Ошибка
  ВЫЗЫВАЮЩЕГО выглядела аварией сервиса, и backend уходил в локальный поиск, считая,
  что сайдкар лёг;
* прислал `{"num_results": 50}` → `min(..., 10)` в теле обработчика молча урезал.
  Граница была, но снаружи её не существовало.

Тесты держат ГРАНИЦУ, а не реализацию: важно, что негодное тело отвергается ДО входа в
обработчик и с указанием поля.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service import main as sidecar

KEY = "test-internal-key"


@pytest.fixture()
def client(monkeypatch):
    """Боевое приложение целиком.

    ⚠️ Именно `service.main.app`, а не собранное здесь из роутера: половина смысла в
    том, что схемы и обработчик ошибок ПОДКЛЮЧЕНЫ. Тест на отдельно собранном
    приложении остался бы зелёным, даже если бы в `main.py` их забыли зарегистрировать.
    """
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)
    monkeypatch.setattr(config.agents, "llm_gateway_enabled", True, raising=False)
    return TestClient(sidecar.app, headers={"Authorization": f"Bearer {KEY}"})


def _post(client, path: str, body: dict):
    return client.post(path, json=body)


# --------------------------------------------------------------------------- #
# Забытое поле — 422 с именем поля, а не «ничего не нашлось»                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("path", "field", "body"),
    [
        ("/tools/web-search", "query", {"num_results": 3}),
        ("/tools/parse-url", "url", {}),
        ("/tools/pptx", "topic", {"model": "gpt-4o-mini"}),
    ],
)
def test_missing_required_field_is_422_naming_it(client, path, field, body):
    """Раньше это был 200 с пустым результатом — вызывающий не узнавал о своей ошибке.

    Все вызывающие (`backend/.../sidecar_tools.py`, media-адаптер) поля шлют всегда,
    поэтому строгость никого не ломает: она называет ошибку вместо того, чтобы её
    прятать.
    """
    resp = _post(client, path, body)

    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"
    assert field in resp.json()["detail"], "в ответе должно быть ИМЯ поля, а не общий текст"


# --------------------------------------------------------------------------- #
# Негодный тип — 422, а не 500                                                  #
# --------------------------------------------------------------------------- #
def test_non_numeric_num_results_is_422_not_500(client):
    """⚠️ Ключевой случай: `int("много")` падал 500.

    Для backend'а 5xx означает «сайдкар лёг» — он уходил в локальный путь и писал
    warning про недоступность, хотя недоступности не было. 422 читается как «чини
    запрос у себя».
    """
    resp = _post(client, "/tools/web-search", {"query": "погода", "num_results": "много"})

    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


@pytest.mark.parametrize("value", [0, -5, 11, 100])
def test_num_results_outside_contract_is_rejected(client, value):
    """Границы объявлены в схеме, значит видны снаружи и проверяются на входе.

    Верхняя раньше молча урезалась (`min(..., 10)`), нижней не было вовсе: ноль и минус
    доезжали до поиска, где условие набора `len(results) >= -5` истинно сразу — то есть
    пустой ответ вместо отказа.
    """
    resp = _post(client, "/tools/web-search", {"query": "погода", "num_results": value})

    assert resp.status_code == 422


def test_num_results_at_bounds_is_accepted():
    """Границы ВКЛЮЧИТЕЛЬНЫ: 1 и 10 годные.

    Проверяем схемой напрямую — тут предмет именно валидация, а не поход в сеть.
    """
    from service.schemas.tools import WebSearchRequest

    assert WebSearchRequest(query="x", num_results=1).num_results == 1
    assert WebSearchRequest(query="x", num_results=10).num_results == 10
    assert WebSearchRequest(query="x").num_results == 5, "дефолт остаётся прежним"


# --------------------------------------------------------------------------- #
# Годное тело доезжает до инструмента                                           #
# --------------------------------------------------------------------------- #
def test_valid_body_reaches_the_tool(client, monkeypatch):
    """Обратная сторона строгости: годный запрос обязан проходить.

    Без этого «отвергать всё» тоже было бы зелёным.
    """
    import importlib

    # ⚠️ Именно `import_module`, а не `import service.domain.tools.web_search as ws`:
    # пакет `tools` реэкспортирует одноимённую ФУНКЦИЮ, и форма с `as` возьмёт атрибут
    # пакета, то есть функцию вместо модуля. Обработчик же берёт атрибут у модуля.
    ws = importlib.import_module("service.domain.tools.web_search")

    seen: dict = {}

    async def _fake(query: str, num_results: int = 5):
        seen["query"] = query
        seen["num_results"] = num_results
        return [{"url": "https://example.com", "title": "t", "snippet": "s"}]

    monkeypatch.setattr(ws, "web_search", _fake)

    resp = _post(client, "/tools/web-search", {"query": "  погода  ", "num_results": 7})

    assert resp.status_code == 200
    assert resp.json()["results"][0]["url"] == "https://example.com"
    assert seen == {"query": "погода", "num_results": 7}, "обрезка пробелов сохранена"


def test_pptx_endpoint_is_a_non_executing_compatibility_tombstone(client):
    resp = _post(client, "/tools/pptx", {"topic": "   "})

    assert resp.status_code == 410
    assert resp.json()["error"] == "tool_unavailable"
