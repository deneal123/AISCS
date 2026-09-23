"""Выбор реализации движка агента по флагу ``AGENTS__ENGINE_MODE``.

Единая точка выбора между in-process движком (текущее поведение) и HTTP-движком,
который стримит на сайдкар ``agents`` (Фаза 4 плана выноса flickering-knitting-wirth).
Централизует переключение, чтобы миграция была ОБРАТИМОЙ: воркер зовёт эту фабрику
вместо прямого ``DefaultAgentExecutionService()``.
"""

from __future__ import annotations

from typing import Any

from service.infrastructure.agents_client.ports import AgentExecutionPort


def _is_canary_user(config: Any, user_id: Any) -> bool:
    """Входит ли пользователь в канареечный список ``AGENTS__ENGINE_CANARY_USER_IDS``.

    Канарейка нужна, чтобы проверить http-путь на ЖИВОМ UI (WS-стрим, биллинг, персист)
    на своём аккаунте, НЕ переводя на сайдкар всех. Сравниваем строками: user_id
    приезжает то UUID-ом, то int, то строкой.
    """
    if user_id is None:
        return False
    raw = str(getattr(config.agents, "engine_canary_user_ids", "") or "")
    if not raw.strip():
        return False
    allowed = {part.strip() for part in raw.split(",") if part.strip()}
    return str(user_id).strip() in allowed


def uses_http_engine(config: Any, user_id: Any = None) -> bool:
    """Пойдёт ли ЭТОТ запрос в сайдкар: глобальный ``http``-режим ИЛИ канарейка.

    Отдельная функция, потому что решение нужно не только фабрике: воркер по нему
    понимает, надо ли класть в тело презайнед-ссылки на табличные файлы (Фаза 0b.4) —
    иначе у канареечного пользователя отвалилась бы аналитика файлов.
    """
    mode = str(getattr(config.agents, "engine_mode", "inprocess") or "inprocess").strip().lower()
    return mode == "http" or _is_canary_user(config, user_id)


def select_agent_engine(config: Any | None = None, user_id: Any = None) -> AgentExecutionPort:
    """Вернуть движок агента: ``HttpAgentEngine`` — стрим ``POST /run`` на сайдкар.

    Режим остался ОДИН. ``"inprocess"`` отвергается явной ошибкой: домен физически
    уехал в сайдкар, и заглушка-фолбэк здесь выглядела бы рабочей деградацией, а на
    деле упала бы импортом отсутствующего кода.
    """
    if config is None:
        from service.settings import Config

        config = Config()

    if uses_http_engine(config, user_id):
        from service.infrastructure.agents_client.http_agent_engine import HttpAgentEngine

        return HttpAgentEngine(config)

    # Ветки "inprocess" БОЛЬШЕ НЕТ: домен физически уехал в сайдкар, backend его
    # исполнить не может. Оставлять заглушку-фолбэк здесь опаснее, чем убрать: она
    # выглядела бы как рабочая деградация, а на деле упала бы импортом.
    raise RuntimeError(
        "AGENTS__ENGINE_MODE=inprocess больше не поддерживается: движок исполняется "
        "только сайдкаром agents. Уберите переменную или задайте http."
    )
