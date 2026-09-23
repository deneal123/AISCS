"""Окружение прогона для http-сайдкара: то, что знает ТОЛЬКО backend.

Снимки политики провайдеров и админ-overlay живут в БД и Redis backend'а — сайдкар туда
не ходит. Едут они отдельным словарём kwargs, а не аргументами движка: in-process движок
таких параметров не знает, и добавлять ему параметры-пустышки ради транспорта незачем.

Вынесено из `process_agent_message_async` — функция давно за потолком храповика, а этот
кусок самостоятелен: ничего из её локальных переменных ему не нужно.

⚠️ Оба снимка fail-open, но НЕ молча. Тихо потерянный снимок — это не пустяк: без
политики снятый админом провайдер снова принимал бы трафик, без overlay настройки из
админки в http-режиме молча перестали бы действовать.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def build_engine_env(
    redis_client: Any = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    files: list[dict] | None = None,
    session_data: dict[str, Any] | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    """Собрать окружение прогона для тела `/run`.

    ⚠️ Песочница выдаётся ТОЛЬКО при переданных `thread_id`/`user_id`: она привязана к
    треду, и без них её некуда привязать. Вызывающий без этих данных получает прежнее
    поведение — шесть инструментов `ws_*` отсеются гейтом с причиной.
    """
    env: dict[str, Any] = {}

    try:
        from service.infrastructure import provider_policy_store as provider_policy
        from service.infrastructure.agents_client.provider_policy_snapshot import build_snapshot

        env["provider_policy"] = build_snapshot(
            disabled=provider_policy.disabled_providers(),
            blocked=await provider_policy.blocked_providers(),
        )
    except Exception:
        logger.warning(
            "снимок провайдерной политики не собран — сайдкар пойдёт по "
            "умолчанию «никто не выключен»",
            extra={"component": "provider_policy", "failure_code": "unavailable"},
        )

    try:
        from service.services.admin.application.runtime_settings import (
            runtime_settings as _admin_runtime_settings,
        )

        env["agent_settings"] = _admin_runtime_settings.snapshot_agents()
    except Exception:
        logger.warning(
            "слепок admin-настроек агентов не собран — сайдкар пойдёт по дефолтам конфига",
            extra={"component": "agent_settings", "failure_code": "unavailable"},
        )

    env["mcp_server_ids"] = _allowed_mcp_servers(env.get("agent_settings"))

    # 🔴 СОГЛАСИЕ НА ДОРОГОЕ — ИЗ ЭТОГО СООБЩЕНИЯ, а не из настройки треда. Просмотр ролика
    # это сотня кадров, переезжающих в контекст каждого следующего сообщения; «включил
    # один раз — смотрит всегда» означало бы, что человек согласился один раз, а платит за
    # каждый ход. Признак ставится нажатием кнопки и живёт ровно один прогон.
    env["video_tool_enabled"] = bool((session_data or {}).get("watch_video"))

    try:
        from service.infrastructure.workspace_client import ensure_workspace, import_files

        ref = await ensure_workspace(redis_client, thread_id, user_id)
        if ref:
            # The opaque agent capability travels only as execution context.  It
            # is not copied into prompts, trace events, or persisted metadata.
            try:
                from service.services.chat.application.workspace_collaboration import (
                    mint_capability,
                )

                ref = {
                    **ref,
                    "coordination_capability": mint_capability(
                        str(ref["workspace_id"]),
                        role="agent",
                        actor_seed=f"{thread_id}:{user_id}",
                        expires_at=float(ref.get("expires_at") or 0),
                        run_id=str(thread_id or ""),
                    ),
                }
            except Exception:
                # A coordinator rollout must not make the existing workspace
                # allocation path fail-open or turn a normal chat into an error.
                logger.warning(
                    "workspace coordination capability was not minted",
                    extra={"component": "workspace", "failure_code": "capability"},
                )
            env["workspace_ref"] = ref
            if agent_run_id and ref.get("coordination_capability"):
                # The room owns this short-lived mapping in Redis. It lets a
                # user cancel the active agent through the existing cooperative
                # worker seam without exposing a Celery identifier in the UI.
                try:
                    from service.services.chat.application.workspace_collaboration import (
                        WorkspaceCollaborationStore,
                    )

                    store = WorkspaceCollaborationStore(
                        redis_client,
                        workspace_id=str(ref["workspace_id"]),
                        expires_at=float(ref.get("expires_at") or 0),
                        thread_id=str(thread_id or ""),
                    )
                    await store.register_agent_run(str(agent_run_id))
                except Exception:
                    logger.warning(
                        "workspace active run was not registered",
                        extra={"component": "workspace", "failure_code": "coordination"},
                    )
            # Файлы пользователя — ССЫЛКАМИ, качает сайдкар. Список тот же, что собран для
            # табличного инструмента: второе представление тех же данных однажды разошлось бы.
            await import_files(ref, files)
    except Exception:
        # Песочницы просто не будет — инструменты отсеются гейтом. Ронять чат нельзя.
        logger.warning(
            "песочница треду не выдана",
            extra={"component": "workspace", "failure_code": "unavailable"},
        )

    return env


async def clear_workspace_active_run(
    env: dict[str, Any] | None, agent_run_id: str | None, redis_client: Any
) -> None:
    """Remove the private active-run mapping once worker finalization finishes."""
    ref = (env or {}).get("workspace_ref") if isinstance(env, dict) else None
    if not isinstance(ref, dict) or not ref.get("coordination_capability") or not agent_run_id:
        return
    try:
        from service.services.chat.application.workspace_collaboration import (
            WorkspaceCollaborationStore,
        )

        store = WorkspaceCollaborationStore(
            redis_client,
            workspace_id=str(ref.get("workspace_id") or ""),
            expires_at=float(ref.get("expires_at") or 0),
            thread_id=str(ref.get("thread_id") or ""),
        )
        await store.clear_agent_run(str(agent_run_id))
    except Exception:
        logger.debug(
            "workspace active run was not cleared",
            extra={"component": "workspace", "failure_code": "cleanup"},
        )


def _allowed_mcp_servers(agent_settings: Any) -> list[str]:
    """Какие MCP-серверы разрешены этому прогону — ИДЕНТИФИКАТОРАМИ, не адресами.

    🔴 РАЗРЕШЕНИЕ И АДРЕС — РАЗНЫЕ ВЕЩИ, и здесь едет только первое. Этот список отвечает
    на вопрос «к каким серверам можно подключаться», и адресу в нём места нет: расширь его
    до URL — и появится поле, ведущее в произвольный хост, то есть SSRF во внутреннюю сеть,
    где Postgres, Redis, MinIO, Qdrant и все сайдкары доступны по топологии без пароля.

    ⚠️ ЧТО ЗДЕСЬ РАНЬШЕ БЫЛО НАПИСАНО НЕВЕРНО. Стояло «адрес не едет в теле НИКОГДА» — и
    это неправда, поймано первым же прогоном написанного стража: адреса и токены MCP уезжают
    рядом, внутри `agent_settings`. Иначе и быть не может — к серверам подключается САЙДКАР,
    и без адреса ему подключаться не к чему (`infrastructure/mcp/runtime.py` берёт их именно
    оттуда). Настоящая защита не в том, что адрес не едет, а в том, что его задаёт АДМИН, а
    не арендатор: пользовательского пути к этому полю нет ни одного.

    ⚠️ Секрет при этом идёт только внутренней сетью между backend и сайдкаром: тело `/run`
    не логируется и в события прогона не попадает. Появится логирование тела — секрет надо
    будет вырезать здесь, и это первое место, куда смотреть.

    ⚠️ Персонального разрешения СЕГОДНЯ НЕ СУЩЕСТВУЕТ — его негде задать: ни колонки в БД,
    ни экрана в панели. Значит разрешение = тумблер админа у самого сервера, и приезжает
    ровно то, что он включил. Пересечение на стороне сайдкара при этом не декоративно: как
    только персональное разрешение появится, сузить набор нужно будет в одном месте, здесь.
    Ничего не объявлено — приедет пусто, и MCP не задействован вовсе.
    """
    declared = agent_settings.get("mcp_servers") if isinstance(agent_settings, dict) else None
    if not isinstance(declared, list):
        return []
    ids = [
        str(item.get("id") or "").strip()
        for item in declared
        if isinstance(item, dict) and item.get("enabled", True)
    ]
    return [server_id for server_id in ids if server_id]
