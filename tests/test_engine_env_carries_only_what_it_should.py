"""Окружение прогона: что уезжает сайдкару и, главное, что НЕ уезжает.

🔴 ЗДЕСЬ ЖИВЁТ ИНВАРИАНТ БЕЗОПАСНОСТИ, у которого не было стража: список РАЗРЕШЁННЫХ
MCP-серверов не разрастается до адресов. Поле, ведущее в произвольный URL, — это SSRF во
внутреннюю сеть, где Postgres, Redis, MinIO, Qdrant и все сайдкары доступны по топологии
без пароля.

⚠️ ПЕРВАЯ РЕДАКЦИЯ ЭТОГО ФАЙЛА ОПИРАЛАСЬ НА ЛОЖНОЕ УТВЕРЖДЕНИЕ и сразу покраснела — к
счастью. В коде было написано «адрес не едет в теле НИКОГДА»; на деле адреса и токены
уезжают рядом, внутри `agent_settings`, и иначе быть не может: к серверам подключается
САЙДКАР. Защита не в том, что адрес не едет, а в том, что его задаёт АДМИН — пользовательского
пути к этому полю нет ни одного. Урок общий: страж, написанный ПО КОММЕНТАРИЮ, проверяет
чужое утверждение, а не поведение, и первым делом выясняет, правда ли оно.

⚠️ Покрытие модуля было 18% — самое низкое в backend, при том что через него проходит каждый
агентский ход: снимок политики провайдеров, админ-настройки, песочница, согласие на видео.

⚠️ Оба снимка fail-open, но НЕ молча, и это тоже правило: тихо потерянный снимок политики
означает, что снятый админом провайдер снова принимает трафик.
"""

from __future__ import annotations

import logging

import pytest

from service.services.chat.infrastructure.chat_worker.engine_env import (
    _allowed_mcp_servers,
    build_engine_env,
)

_LOGGER_NAME = "service.services.chat.infrastructure.chat_worker.engine_env"


@pytest.fixture(autouse=True)
def _logs_actually_reach_caplog(caplog):
    """Записи модуля обязаны доезжать до `caplog` НЕЗАВИСИМО ОТ ПОРЯДКА ТЕСТОВ.

    🔴 ТРИ ТЕСТА ЭТОГО ФАЙЛА БЫЛИ ЗЕЛЁНЫМИ В ОДИНОЧКУ И КРАСНЫМИ В НАБОРЕ. Причина: `LOGGING`
    в настройках объявляет логгер `service` с `propagate: False`, а `service/main.py`
    применяет этот dictConfig на импорте. Стоит соседнему тесту импортировать `main` раньше —
    и записи не доходят до корневого перехватчика pytest. Проверка «отказ не молчит»
    превращалась в «лога нет»: страж падал по причине, к правилу не относящейся.

    ⚠️ ЦЕПЛЯЕМ ХЕНДЛЕР ПРЯМО К ЛОГГЕРУ, а не правим `propagate`: правка проброса лечит
    следствие и ломает то, ради чего его выключили. Тот же приём уже применён в
    `test_charge_usage_anomaly` и `test_worker_task_forward_compat` — третий случай, значит
    свойство общее: у backend логи НЕ ПРОБРАСЫВАЮТСЯ, и тест обязан это учитывать сам.

    ⚠️ Обратный случай ничем не лучше: соседняя настройка могла бы и СКРЫТЬ поломку, оставив
    стража зелёным. Тест, зависящий от порядка запуска, — не страж, а лотерея.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)


# --- MCP: только идентификаторы --------------------------------------------------------- #

DECLARED = {
    "mcp_servers": [
        {
            "id": "internal-wiki",
            "url": "http://10.0.0.5:8080/mcp",
            "auth_token": "секрет-который-нельзя-отдавать",
            "enabled": True,
        },
        {"id": "выключенный", "url": "http://10.0.0.6", "enabled": False},
    ]
}


def test_only_identifiers_travel_never_addresses():
    """🔴 ГЛАВНОЕ. Уезжает `internal-wiki`, а не `http://10.0.0.5:8080/mcp`."""
    ids = _allowed_mcp_servers(DECLARED)

    assert ids == ["internal-wiki"]


@pytest.mark.asyncio
async def test_the_permission_list_never_grows_into_addresses(monkeypatch):
    """🔴 ПРОВЕРЯЕМ ИМЕННО СПИСОК РАЗРЕШЕНИЙ. Он отвечает на вопрос «к каким серверам можно»,
    и адресу в нём места нет: расширь его до URL — появится поле, ведущее в произвольный
    хост, то есть SSRF во внутреннюю сеть.

    ⚠️ ПЕРВАЯ РЕДАКЦИЯ ЭТОГО ТЕСТА ПРОВЕРЯЛА НЕ ТО и сразу покраснела — к счастью. Она
    требовала, чтобы адреса не было в теле ЦЕЛИКОМ, опираясь на комментарий «адрес не едет
    НИКОГДА». Комментарий врал: адреса и токены уезжают рядом, внутри `agent_settings`, и
    иначе быть не может — к серверам подключается САЙДКАР, без адреса ему некуда. Настоящая
    защита не в том, что адрес не едет, а в том, что его задаёт АДМИН: пользовательского
    пути к этому полю нет ни одного. Комментарий исправлен, тест проверяет настоящее правило.
    """
    monkeypatch.setattr(
        "service.services.admin.application.runtime_settings.runtime_settings.snapshot_agents",
        lambda: DECLARED,
    )

    env = await build_engine_env()

    assert env["mcp_server_ids"] == ["internal-wiki"]
    ids = repr(env["mcp_server_ids"])
    assert "10.0.0.5" not in ids, "в список разрешений просочился адрес — это SSRF-поверхность"
    assert "секрет" not in ids, "в список разрешений просочился секрет сервера"
    assert "http" not in ids, "в списке разрешений появился URL — он обязан быть именами"


def test_a_disabled_server_is_not_offered():
    """Выключенный админом сервер — это «его нет для прогона», а не «есть, но неактивен»."""
    assert "выключенный" not in _allowed_mcp_servers(DECLARED)


def test_nothing_declared_means_mcp_is_not_used():
    """⚠️ Пусто — не ошибка: MCP просто не задействован."""
    assert _allowed_mcp_servers(None) == []
    assert _allowed_mcp_servers({}) == []
    assert _allowed_mcp_servers({"mcp_servers": "не список"}) == []


def test_a_server_without_an_id_is_dropped():
    """Сервер без идентификатора нечем сопоставить с адресом на той стороне."""
    assert _allowed_mcp_servers({"mcp_servers": [{"url": "http://x", "enabled": True}]}) == []
    assert _allowed_mcp_servers({"mcp_servers": [{"id": "   ", "enabled": True}]}) == []


def test_a_server_without_an_explicit_flag_counts_as_enabled():
    """⚠️ Отсутствие поля — не «выключен»: иначе admin-запись без флага молча пропадала бы."""
    assert _allowed_mcp_servers({"mcp_servers": [{"id": "s1"}]}) == ["s1"]


# --- согласие на дорогое ---------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_video_consent_comes_from_this_message_only():
    """🔴 «Включил один раз — смотрит всегда» означало бы, что человек согласился однажды, а
    платит за каждый следующий ход."""
    assert (await build_engine_env(session_data={"watch_video": True}))["video_tool_enabled"]
    assert not (await build_engine_env(session_data={"watch_video": False}))["video_tool_enabled"]
    assert not (await build_engine_env(session_data={}))["video_tool_enabled"]
    assert not (await build_engine_env())["video_tool_enabled"]


# --- fail-open, но не молча ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_lost_policy_snapshot_is_logged_not_swallowed(monkeypatch, caplog):
    """🔴 Тихо потерянный снимок политики = снятый админом провайдер снова принимает трафик.

    Ход при этом ронять нельзя — поэтому именно fail-open И запись в лог, а не одно из двух.

    ⚠️ ПРОВЕРЯЕМ, ЧТО ОТКАЗ ВЫЗВАН НАШЕЙ ПОДМЕНОЙ. Без этого тест зелен и по другой причине:
    в тестовом окружении Redis может быть недоступен, снимок не собрался бы сам, и
    утверждение «ключа нет» не значило бы ничего. Тот же класс уже ловил меня трижды.
    """
    called = []

    def _boom():
        called.append(True)
        raise RuntimeError("политика недоступна")

    monkeypatch.setattr("service.infrastructure.provider_policy_store.disabled_providers", _boom)

    with caplog.at_level("WARNING"):
        env = await build_engine_env()

    assert called, "подмена не вызывалась — отказ пришёл откуда-то ещё, тест не о том"
    assert "provider_policy" not in env, "снимок собрался вопреки сбою"
    assert any("политик" in r.message.lower() for r in caplog.records), (
        "снимок потерян МОЛЧА — узнать об этом было бы нельзя"
    )


@pytest.mark.asyncio
async def test_a_lost_admin_snapshot_is_logged_not_swallowed(monkeypatch, caplog):
    """Без overlay настройки из админки в http-режиме молча перестают действовать.

    ⚠️ Здесь «ключа нет» — уже доказательство: не упавший снимок положил бы в окружение
    хотя бы пустой словарь. Но `called` оставляем ради явности, а не веры в это рассуждение.
    """
    called = []

    def _boom():
        called.append(True)
        raise RuntimeError("overlay недоступен")

    monkeypatch.setattr(
        "service.services.admin.application.runtime_settings.runtime_settings.snapshot_agents",
        _boom,
    )

    with caplog.at_level("WARNING"):
        env = await build_engine_env()

    assert called, "подмена не вызывалась — тест не о том"
    assert "agent_settings" not in env
    assert any("admin" in r.message.lower() for r in caplog.records)


# --- песочница -------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_sandbox_without_a_thread_and_a_user(monkeypatch):
    """⚠️ Песочница привязана к ТРЕДУ: без него её некуда привязать, и просить незачем."""
    asked = []

    async def _ensure(_redis, thread_id, user_id):
        asked.append((thread_id, user_id))
        return None

    monkeypatch.setattr("service.infrastructure.workspace_client.ensure_workspace", _ensure)

    env = await build_engine_env()

    assert "workspace_ref" not in env
    assert asked == [(None, None)], "запрос ушёл с пустыми идентификаторами и создал бы мусор"


@pytest.mark.asyncio
async def test_files_are_imported_into_the_granted_sandbox(monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА. Ссылка без импорта = пустой рабочий каталог при «приложенном» файле."""
    imported = {}

    async def _ensure(_redis, thread_id, user_id):
        return {"workspace_id": "w-1", "token": "t", "user_id": user_id, "thread_id": thread_id}

    async def _import(ref, files):
        imported.update({"ref": ref["workspace_id"], "files": files})
        return len(files or [])

    monkeypatch.setattr("service.infrastructure.workspace_client.ensure_workspace", _ensure)
    monkeypatch.setattr("service.infrastructure.workspace_client.import_files", _import)

    env = await build_engine_env(None, "t-1", "u-1", [{"name": "смета.txt", "url": "https://s/1"}])

    assert env["workspace_ref"]["workspace_id"] == "w-1"
    assert imported["ref"] == "w-1"
    assert [f["name"] for f in imported["files"]] == ["смета.txt"]


@pytest.mark.asyncio
async def test_a_broken_sandbox_does_not_break_the_turn(monkeypatch, caplog):
    """⚠️ Инструменты отсеются гейтом с причиной — ронять из-за этого чат нельзя."""

    async def _boom(*_a):
        raise RuntimeError("сайдкар песочницы лёг")

    monkeypatch.setattr("service.infrastructure.workspace_client.ensure_workspace", _boom)

    with caplog.at_level("WARNING"):
        env = await build_engine_env(None, "t-1", "u-1", [])

    assert "workspace_ref" not in env
    assert isinstance(env, dict), "ход упал из-за недоступной песочницы"
    assert any("песочниц" in r.message.lower() for r in caplog.records)
