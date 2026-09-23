"""Все ручки сайдкара, кроме `/health`, закрыты ключом.

⚠️ Почему это отдельный файл, а не строчка в чужом тесте. `/run` несёт полный
пользовательский контекст, историю переписки, память и терминальный result-dict, из
которого backend СПИСЫВАЕТ ДЕНЬГИ, а `/providers/keys` ПРИНИМАЕТ ключи провайдеров
платформы. Обе были открыты для всего, что дотянулось до внутренней сети.

⚠️ Открыты они были не по недосмотру, а из-за ПРАВИЛА ПРОВЕРКИ. Ручки пользовались
проверкой шлюза `/v1`, у которой пустой ключ означает «пропустить всех» (dev-режим), —
то есть при незаполненном `AGENTS__LLM_GATEWAY_API_KEY` дверь открыта, и выглядит это
как рабочая конфигурация. Вторая половина той же беды: та же проверка отдаёт 404 при
`llm_gateway_enabled=false`, так что выключение ЧУЖОЙ функции гасило приём ключей и
инструменты, а вызывающий читал 404 как «такой ручки нет».

Поэтому здесь два разных теста: поимённые (401/503 по HTTP) и СПЛОШНОЙ обход всех
маршрутов приложения — второй ловит то, чего поимённые не умеют: новую ручку, добавленную
без авторизации. Дырка находилась дважды именно так, поэтому проверка структурная.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.presentation.routers.agent import route as route_api
from service.presentation.routers.agent import run as run_api

KEY = "test-internal-key"

# Ручки, которым ключ не нужен, — каждая с причиной. Список ЗАКРЫТЫЙ: сплошной обход
# ниже сверяет его на равенство, поэтому новая ручка не может тихо в него попасть.
OPEN_PATHS = {
    # Хелсчек compose. Требовать здесь ключ значило бы отдать здоровье контейнера на
    # откуп конфигурации секретов: не доехал ключ — контейнер вечно «нездоров».
    "/health",
    # Схема и её просмотрщики — служебное от FastAPI, данных не носят.
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

# ⚠️ `/v1` живёт по ЧУЖОМУ протоколу и имеет собственную проверку с собственными
# правилами (dev-режим при пустом ключе там осмыслен: это OpenAI-совместимый шлюз,
# который в разработке поднимают без секретов). Исключение названо здесь, чтобы
# отличаться от недосмотра.
FOREIGN_PROTOCOL_PREFIX = "/v1"


@pytest.fixture()
def client(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)
    app = FastAPI()
    app.include_router(run_api.router)
    app.include_router(route_api.router)
    return TestClient(app)


def _body() -> dict:
    return {"text": "привет", "thread_id": "t1"}


def test_run_without_key_is_401(client):
    assert client.post("/run", json=_body()).status_code == 401


def test_run_with_wrong_key_is_401(client):
    resp = client.post("/run", json=_body(), headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_run_with_correct_key_passes_auth(client):
    """С верным ключом запрос ПРОХОДИТ авторизацию.

    Дальше он может упасть на отсутствии движка (503) — это нормально и даже полезно:
    важно, что 401 больше нет, то есть проверка ключа не превратилась в «запрещено
    всегда».
    """
    resp = client.post("/run", json=_body(), headers={"Authorization": f"Bearer {KEY}"})

    assert resp.status_code != 401


def test_route_without_key_is_401(client):
    assert client.post("/route", json={"text": "привет"}).status_code == 401


def test_empty_key_is_rejected_not_allowed(monkeypatch):
    """Ключ не настроен → 503, а НЕ «пускаем всех».

    ⚠️ Ровно этим `internal_auth` отличается от проверки шлюза `/v1`: у той пустой ключ
    открывает ручку. Открытая дверь по умолчанию не должна выглядеть как рабочая
    конфигурация — `.env.example` ключ поставляет, так что отказ никого не ломает.
    """
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", "", raising=False)
    app = FastAPI()
    app.include_router(run_api.router)

    resp = TestClient(app).post("/run", json=_body())

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_correlation_id_from_header_is_applied(client, monkeypatch):
    """Идентификатор из заголовка ДОЛЖЕН попасть в контекст сайдкара.

    ⚠️ Проверяется вызовом, а не чтением ContextVar после запроса: контекст живёт
    внутри обработки, и снаружи он всегда None — такая «проверка» была бы зелёной
    независимо от того, работает ли проброс. Первая попытка была именно такой.

    Смысл цепочки: backend ставит id (`set_correlation_context` в воркере) → шлёт
    заголовком → сайдкар подхватывает → его собственные клиенты (duckdb и др.) несут
    дальше. Без этого историю одного вопроса нельзя собрать из логов трёх сервисов.
    """
    seen: list[str | None] = []
    monkeypatch.setattr(run_api, "set_correlation_id", seen.append)

    client.post(
        "/run",
        json=_body(),
        headers={"Authorization": f"Bearer {KEY}", "X-Correlation-Id": "job-42"},
    )

    assert seen == ["job-42"]


@pytest.mark.parametrize(
    "path", ["/catalog", "/catalog/chat-models", "/catalog/personas", "/providers/health"]
)
def test_metadata_endpoints_are_closed_too(monkeypatch, path):
    """Метаданные тоже за ключом.

    Пользовательских данных здесь нет, но каталог моделей и здоровье провайдеров —
    это разведка о нашей инфраструктуре: кто у нас подключён, что живо, что упало.
    Отдавать её всему, что дотянулось до внутренней сети, незачем.
    """
    from service.presentation.routers.providers import catalog as catalog_api
    from service.presentation.routers.providers import health as providers_health_api
    from service.presentation.routers.providers import keys as provider_keys_api
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)
    app = FastAPI()
    app.include_router(catalog_api.router)
    app.include_router(provider_keys_api.router)
    app.include_router(providers_health_api.router)

    assert TestClient(app).get(path).status_code == 401


def test_health_stays_open(monkeypatch):
    """`/health` остаётся открытым — иначе compose не сможет проверить контейнер."""
    from service.presentation.routers import health as health_api

    app = FastAPI()
    app.include_router(health_api.router)

    assert TestClient(app).get("/health").status_code == 200


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/tools/web-search", {"query": "погода"}),
        ("/tools/parse-url", {"url": "https://example.com"}),
        ("/tools/pptx", {"topic": "тема"}),
        (
            "/media/describe-image",
            {"content_b64": "", "content_type": "image/png", "filename": "a"},
        ),
        ("/media/transcribe", {"content_b64": "", "filename": "a.wav"}),
        ("/vector/index", {"user_id": "1", "filename": "a.txt", "text": "текст"}),
        ("/vector/search", {"user_id": "1", "query": "что-то"}),
        ("/vector/delete", {"user_id": "1"}),
        ("/providers/keys", {"version": 1, "overrides": {}}),
    ],
)
def test_data_and_secret_endpoints_are_closed(monkeypatch, path, body):
    """Инструменты, память, медиа и ПРИЁМ КЛЮЧЕЙ ПРОВАЙДЕРОВ — за ключом.

    ⚠️ `/providers/keys` тут главный: она принимает ключи провайдеров платформы. Пока
    она проверялась функцией шлюза, при пустом `AGENTS__LLM_GATEWAY_API_KEY` кто угодно
    из внутренней сети мог направить трафик платформы на свой ключ или снести
    override'ы — молча, потому что снаружи это выглядит как обычное применение снимка.
    """
    from service import main as sidecar
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)

    assert TestClient(sidecar.app).post(path, json=body).status_code == 401


def test_auth_runs_before_anything_else(monkeypatch):
    """Проверка ключа — ПЕРВОЕ, что делает ручка.

    ⚠️ Раньше она стояла после загрузки движка (у `/vector/*` — после проверки
    хранилища), и неавторизованный запрос успевал узнать, поднят ли сервис: 503 и 401
    различимы снаружи. Признак правильного порядка — 401 приходит и тогда, когда
    зависимость заведомо мертва.
    """
    from service.presentation import runtime
    from service.presentation.routers.capabilities import vector as vector_api
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)
    monkeypatch.setattr(runtime, "vector_store", lambda: None)
    app = FastAPI()
    app.include_router(vector_api.router)

    resp = TestClient(app).post("/vector/search", json={"user_id": "1", "query": "x"})

    assert resp.status_code == 401, "хранилища нет, но снаружи это знать не положено"


# --------------------------------------------------------------------------- #
# Сплошной обход: НИ ОДНОЙ ручки мимо авторизации                              #
# --------------------------------------------------------------------------- #
def _all_routes():
    """Все маршруты боевого приложения, включая вложенные роутеры.

    ⚠️ Обход рекурсивный не для красоты: в этой версии FastAPI подключённый роутер
    остаётся в `app.routes` объектом-обёрткой, а не разворачивается в плоский список.
    Наивный `for r in app.routes` увидел бы ровно четыре служебных маршрута FastAPI и
    ни одного нашего — и «проверка» была бы зелёной, не проверив ничего.
    """
    from service import main as sidecar

    def walk(routes):
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from walk(original.routes)
            elif getattr(route, "routes", None):
                yield from walk(route.routes)
            elif getattr(route, "path", None):
                yield route

    return list(walk(sidecar.app.routes))


def test_route_walker_actually_sees_our_endpoints():
    """Страховка на сам обход: он обязан находить ручки, иначе проверка ниже пуста."""
    paths = {r.path for r in _all_routes()}

    assert {"/run", "/route", "/tools/pptx", "/vector/index"} <= paths


def test_every_endpoint_requires_a_key():
    """НИ ОДНОЙ ручки мимо `internal_auth`, кроме поимённо открытых.

    Смысл именно в сплошном обходе: поимённые тесты проверяют то, что мы уже вспомнили,
    а дырку оба раза находили в ручке, о которой не вспомнили. Новый эндпоинт без
    авторизации валит этот тест в момент появления, а не на аудите через полгода.
    """
    unprotected = []
    for route in _all_routes():
        if route.path in OPEN_PATHS or route.path.startswith(FOREIGN_PROTOCOL_PREFIX):
            continue
        source = inspect.getsource(route.endpoint)
        if "internal_auth" not in source:
            unprotected.append(route.path)

    assert not unprotected, f"ручки без проверки ключа: {unprotected}"


def test_open_list_is_exhaustive():
    """Список открытых ручек ЗАКРЫТ: сверяем на равенство, а не на вхождение.

    Проверка «⊆» позволила бы новой открытой ручке появиться незамеченной — достаточно
    было бы дописать её в список. Равенство заставляет объяснять КАЖДУЮ открытую дверь.
    """
    actual_open = {
        r.path
        for r in _all_routes()
        if not r.path.startswith(FOREIGN_PROTOCOL_PREFIX)
        and "internal_auth" not in inspect.getsource(r.endpoint)
    }

    assert actual_open == OPEN_PATHS
