"""Полный список ручек сервиса зафиксирован.

⚠️ ЗАЧЕМ. Сборка приложения идёт через ОДИН список `ALL_ROUTERS`, и это правильно —
второе место, где надо помнить о новой ручке, рано или поздно расходится с первым. Но у
единственного списка есть своя цена: роутер, забытый в нём, не падает и не логируется.
Он просто не существует, а вызывающий получает 404 «такой ручки нет» — неотличимо от
опечатки в пути у себя.

Ровно этот риск и реализуется при перестановке файлов: ручки переехали из плоского
`api/` в сгруппированный `presentation/routers/`, и потерять одну по дороге можно было
молча. Список ниже — снимок ДО переезда, сверенный вручную.

Тест намеренно ХРУПКИЙ: новая ручка обязана его уронить. Это не помеха, а смысл —
добавление публичной ручки сервиса не должно проходить незамеченным, у него есть
последствия в авторизации (`test_internal_auth.py`) и в контракте с backend.
"""

from __future__ import annotations

from service import main as sidecar

# Служебное от FastAPI. Данных не носит, но перечислено явно: если схема вдруг перестанет
# отдаваться, это тоже изменение поведения.
FRAMEWORK_PATHS = {
    ("GET,HEAD", "/openapi.json"),
    ("GET,HEAD", "/docs"),
    ("GET,HEAD", "/docs/oauth2-redirect"),
    ("GET,HEAD", "/redoc"),
}

# Ручки сервиса. Сгруппированы так же, как каталоги в `presentation/routers/`.
SERVICE_ROUTES = {
    # хелсчек compose + контракт для сверки с backend
    ("GET", "/health"),
    # agent/ — ядро; обе ручки денежные
    ("POST", "/run"),
    ("POST", "/route"),
    # private backend -> agents visual attestation for Document Forge
    ("POST", "/document-audit"),
    # providers/ — ключи, здоровье, каталог моделей
    ("POST", "/providers/keys"),
    ("GET", "/providers/health"),
    ("GET", "/catalog"),
    ("GET", "/catalog/chat-models"),
    # каталог личностей для селектора: реестром владеет сайдкар, он же его и публикует
    # Каталог агентов: backend использует его только для внутренних проверок способностей.
    ("GET", "/catalog/agents"),
    ("GET", "/catalog/personas"),
    # capabilities/ — возможности движка как ручки
    ("POST", "/tools/web-search"),
    ("POST", "/tools/parse-url"),
    ("POST", "/tools/pptx"),
    ("POST", "/media/describe-image"),
    ("POST", "/media/transcribe"),
    ("POST", "/vector/index"),
    ("POST", "/vector/search"),
    ("POST", "/vector/delete"),
    # Внутренняя outbox-проекция автономного workflow-каталога.
    ("POST", "/workflow-catalog/upsert"),
    ("POST", "/workflow-catalog/delete"),
}

# gateway/ — чужой протокол. Отдельным множеством, потому что его ломать нельзя вообще:
# по нему ходят memos, ldr, graphify и сторонние SDK, которых мы не контролируем.
GATEWAY_ROUTES = {
    ("POST", "/v1/chat/completions"),
    ("GET", "/v1/models"),
    ("POST", "/v1/embeddings"),
}


def _actual() -> set[tuple[str, str]]:
    """Маршруты боевого приложения.

    ⚠️ Обход рекурсивный: в этой версии FastAPI подключённый роутер остаётся в
    `app.routes` объектом-обёрткой, а не разворачивается в плоский список. Наивный цикл
    вернул бы четыре служебных маршрута и ни одного нашего — то есть тест был бы зелёным,
    не проверив ничего.
    """

    def walk(routes):
        for route in routes:
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from walk(original.routes)
            elif getattr(route, "routes", None):
                yield from walk(route.routes)
            elif getattr(route, "path", None):
                yield route

    return {(",".join(sorted(r.methods or [])), r.path) for r in walk(sidecar.app.routes)}


def test_route_table_matches_exactly():
    """Ни одной ручки не потерялось и ни одной не появилось незамеченной."""
    expected = FRAMEWORK_PATHS | SERVICE_ROUTES | GATEWAY_ROUTES
    actual = _actual()

    assert actual == expected, (
        f"пропали: {sorted(expected - actual)}; появились: {sorted(actual - expected)}"
    )


def test_gateway_is_mounted_separately_from_all_routers():
    """⚠️ Шлюза в `ALL_ROUTERS` нет намеренно — он монтируется только если загрузился.

    Движка может не быть (сборка, отсутствующий маунт), и сервис обязан подняться с живым
    `/health`, где видно, ПОЧЕМУ шлюз недоступен. Положить его в общий список значило бы
    уронить весь сервис из-за необязательной части.
    """
    from service.presentation.routers import ALL_ROUTERS

    assembled = {
        (",".join(sorted(r.methods or [])), r.path) for rt in ALL_ROUTERS for r in rt.routes
    }

    assert assembled == SERVICE_ROUTES
    assert not any(path.startswith("/v1") for _, path in assembled)
