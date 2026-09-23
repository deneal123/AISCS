"""Потолок тела запроса — у сайдкара его не было НИ НА ОДНОЙ ручке.

⚠️ ЧЕМ ЭТО ОПАСНО ИМЕННО ЗДЕСЬ. Опаснее всего `/run`: туда приезжают история переписки,
память, резюме и извлечённый текст вложений — тело растёт вместе с активностью
пользователя, а не задаётся кодом. Не ограничивал никто: uvicorn читает тело ЦЕЛИКОМ в
память, прежде чем отдать приложению. Сайдкар при этом ДОЛГОЖИВУЩИЙ и ОДИН на всю
платформу, то есть один достаточно большой запрос кладёт обработку у ВСЕХ.

Остальные три сайдкара (`duckdb`, `whisper`, `opendataloader`) лимит имеют — этот
остался последним.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service import contracts
from service import main as sidecar
from service.presentation import errors

KEY = "test-internal-key"


@pytest.fixture()
def client(monkeypatch):
    """Боевое приложение целиком — предмет теста в том числе ПОДКЛЮЧЕНИЕ middleware.

    ⚠️ На синтетическом приложении тест был бы зелёным и в случае, когда middleware
    написан, но в `service/main.py` не зарегистрирован, — то есть проверял бы функцию,
    а не защиту сервиса.
    """
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_gateway_api_key", KEY, raising=False)
    return TestClient(sidecar.app, headers={"Authorization": f"Bearer {KEY}"})


@pytest.fixture()
def tiny_limit(monkeypatch):
    """Опустить потолок вместо того, чтобы гнать 64 МБ через тест.

    Предмет — механизм отказа, а не конкретное число; само число проверяется отдельно
    (`test_limit_comes_from_contract`).
    """
    monkeypatch.setattr(errors, "MAX_BODY_BYTES", 100)


def test_oversized_body_is_413_in_our_form(client, tiny_limit):
    resp = client.post("/run", json={"text": "я" * 500, "thread_id": "t1"})

    assert resp.status_code == 413
    assert resp.json()["error"] == "request_too_large"


def test_oversized_body_is_rejected_before_the_handler(client, tiny_limit):
    """Отказ ДО обработчика, а не внутри него.

    Смысл лимита в том, чтобы не разбирать огромное тело: проверка внутри ручки
    сработала бы уже после того, как pydantic собрал объект — то есть после расхода
    памяти, ради экономии которой лимит и заводится. Признак — на закрытой ключом
    ручке 413 приходит БЕЗ ключа: авторизация до неё не доходит.
    """
    resp = client.post(
        "/run", json={"text": "я" * 500, "thread_id": "t1"}, headers={"Authorization": ""}
    )

    assert resp.status_code == 413, "лимит обязан отработать раньше авторизации ручки"


def test_normal_body_passes(client, tiny_limit):
    """Обратная сторона: тело в пределах лимита проходит.

    Иначе «отвергать всё» тоже было бы зелёным. Ответ здесь может быть любым (движка в
    тестовом окружении может не быть) — важно, что это НЕ 413.
    """
    resp = client.post("/run", json={"text": "привет", "thread_id": "t1"})

    assert resp.status_code != 413


def test_v1_gets_openai_error_shape(client, tiny_limit):
    """⚠️ Названное отступление: у `/v1` ошибка ОБЪЕКТ, как ждёт OpenAI-SDK.

    Клиенты `/v1` — memos, ldr, graphify и любые сторонние SDK — разбирают
    `{"error": {"message", "type"}}`. Наша плоская форма сломала бы им разбор ошибки
    ровно в тот момент, когда она нужнее всего.
    """
    resp = client.post("/v1/chat/completions", json={"model": "x", "messages": ["я" * 500]})

    assert resp.status_code == 413
    body = resp.json()
    assert isinstance(body["error"], dict)
    assert "message" in body["error"] and "type" in body["error"]


def test_limit_comes_from_contract_and_is_published(client):
    """Число живёт в контракте и видно снаружи, а не зашито в middleware.

    Вызывающий по нему решает, резать ли контекст У СЕБЯ; у остальных сайдкаров оно
    публикуется в `/health` так же.
    """
    assert errors.MAX_BODY_BYTES == contracts.MAX_BODY_BYTES

    published = client.get("/health").json()["contract"]["max_body_bytes"]

    assert published == contracts.MAX_BODY_BYTES


def test_limit_is_overridable_by_env():
    """Потолок настраивается без пересборки образа.

    ⚠️ Читается на импорте модуля: правка переменной у живого процесса не применится —
    нужен рестарт. Значение при этом живёт в НЕСКОЛЬКИХ местах (контракт, ENV образа,
    дефолты compose), и ENV перекрывает контракт.

    ⚠️ ПРОВЕРКА РАЗДЕЛЕНА НА ДВА ШАГА, И ЭТО НЕ ПЕДАНТИЗМ. Значение переехало из
    `os.environ` в поле `AgentsConfig.max_body_bytes`: `extra="forbid"` отвергал
    `AGENTS__MAX_BODY_BYTES` как незаявленную переменную, то есть ОБЪЯВИТЬ лимит значило
    уронить старт обоих сервисов — ровно это и лежало в отслеживаемом
    `docker/.env.example`, делая шаблон непригодным к копированию.

    Соблазн был проверить всё разом: выставить переменную и перезагрузить настройки. Так
    и было сделано в первой версии — и **сломало десять чужих тестов**:
    `importlib.reload(settings)` подменяет глобальный `config`, а патчи, наложенные
    другими тестами на ПРЕЖНИЙ объект, перестают действовать. Перезагрузка модуля с
    синглтоном — это загрязнение всего прогона, а не локальная подмена.
    """
    import importlib

    from service.settings import AgentsConfig, config

    # Шаг 1: переменная окружения ДОХОДИТ до поля (и не отвергается `extra="forbid"`).
    # Свежий экземпляр, а не перезагрузка модуля — глобальный `config` не трогаем.
    fresh = AgentsConfig(_env_file=None, max_body_bytes=12345)
    assert fresh.max_body_bytes == 12345

    # Шаг 2: контракт берёт значение ИЗ КОНФИГА, а не из своего дефолта.
    original = config.agents.max_body_bytes
    try:
        config.agents.max_body_bytes = 12345
        assert importlib.reload(contracts).MAX_BODY_BYTES == 12345
    finally:
        config.agents.max_body_bytes = original
        importlib.reload(contracts)
