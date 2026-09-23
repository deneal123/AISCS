"""Всё, что агент отдаёт пользователю ФАЙЛАМИ, — в одном месте.

Артефактов теперь два источника: те, что субагент положил прямо в метаданные (картинка,
презентация), и те, что агент создал в файловой песочнице. ⚠️ Мост у них ОДИН и тот же —
второй способ отдать пользователю файл означал бы второе место, где чинить владельца,
хранилище и запись в `generated_files`.

Вынесено из `process_agent_message_async`: функция давно за потолком храповика, а этот узел
самостоятелен — из её локальных переменных ему нужны только служба файлов и идентификаторы.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _collectable_workspace_inventory(inventory: Any) -> list[dict[str, Any]]:
    """Exclude Document Forge projects from the legacy eager artifact bridge.

    A document project contains source, profile and vendor files.  Only an audited
    PDF/source bundle descriptor may enter its durable publication outbox; treating
    every new project file as a user download creates phantom artifacts on failed
    builds and bypasses the final audit.
    """

    output: list[dict[str, Any]] = []
    for item in inventory if isinstance(inventory, list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        if not path or path == "documents" or path.startswith("documents/"):
            continue
        if any(part.startswith(".gpthub-document") for part in path.split("/")):
            continue
        output.append(item)
    return output


async def _persist_document_artifacts(
    file_service,
    user_id: Any,
    metadata: dict[str, Any],
    workspace_ref: dict[str, Any] | None,
) -> None:
    """Convert private artifact descriptors into a transaction-bound outbox intent."""
    descriptors = metadata.pop("document_artifacts", None)
    if not workspace_ref or not isinstance(descriptors, list):
        return
    from service.services.chat.persistence.document_publications import normalize_descriptors

    normalized = normalize_descriptors(descriptors)
    if normalized:
        metadata["_document_publications"] = list(normalized)


async def _forget_dead_binding(thread_id: str) -> None:
    """Стереть привязку к песочнице, которой доказанно нет.

    ⚠️ КЛИЕНТ REDIS БЕРЁМ СВОЙ, а не тащим сквозь весь путь обработки хода: у воркера он
    синхронный, у веб-процесса асинхронный, и ради одной строки лечения пришлось бы
    протаскивать его через четыре подписи в функцию, которая давно за потолком храповика.
    `forget_binding` умеет оба вида клиента, а тред ссылка знает сама.
    """
    from service.infrastructure.cache.redis_manager import RedisManager
    from service.infrastructure.workspace_client import forget_binding
    from service.settings import config

    try:
        await forget_binding(RedisManager(config.redis).get_client(), thread_id)
    except Exception:  # noqa: BLE001 — Redis выключен или лёг: следующий ход разберётся сам
        logger.debug(
            "мёртвая привязка песочницы не стёрта",
            extra={"component": "workspace", "failure_code": "cleanup"},
        )


async def snapshot_workspace(engine_env: dict[str, Any] | None, user_text: str) -> None:
    """Зафиксировать состояние песочницы после хода — снимком в её истории.

    🔴 БЕЗУСЛОВНО, а не «если агент что-то создал». Опись артефактов перечисляет НОВЫЕ
    файлы; правка импортированного в неё не попадает вовсе, и именно её восстановить
    было бы нечем. Пустой ход сайдкар отличает сам («нечего фиксировать»).

    Сообщение снимка — ЗАПРОС ЧЕЛОВЕКА: по такой истории видно, что происходило, а не
    «commit 1, commit 2».

    Best-effort: снимок не сделался — ответ пользователю от этого не страдает.

    🔴 ЗАОДНО ЭТО ЕДИНСТВЕННАЯ ПРОВЕРКА ЖИВОСТИ НА ХОД. Реестр сайдкара живёт в памяти:
    после его перезапуска привязки всех тредов указывают в пустоту СРАЗУ, а ключи в Redis
    протухнут лишь к концу своего срока — до получаса каждый ход честно поднимает файловые
    инструменты, и каждый их вызов отвечает «песочницы нет». Здесь мы узнаём правду
    (снимок делается ПОСЛЕ КАЖДОГО хода, а не только когда есть файлы) — и стираем
    привязку, чтобы следующий ход создал новую песочницу вместо похода к мёртвой.
    """
    ref = (engine_env or {}).get("workspace_ref")
    if not ref:
        return
    from service.infrastructure.workspace_client import WorkspaceGone, snapshot

    try:
        result = await snapshot(ref, "agent_run")
    except WorkspaceGone:
        logger.warning(
            "песочница треда пропала — привязка стёрта, следующий ход создаст новую",
            extra={"component": "workspace", "failure_code": "expired"},
        )
        await _forget_dead_binding(str(ref.get("thread_id") or ""))
        return
    except Exception:  # noqa: BLE001 — история версий не повод ронять ответ
        logger.debug(
            "снимок песочницы не сделан",
            extra={"component": "workspace", "failure_code": "snapshot"},
        )
        return
    reason = (result or {}).get("reason")
    # ⚠️ «Нет git» — НЕ то же, что «нечего фиксировать»: первое означает, что истории нет
    # вовсе и откат никогда не сработает. Молчать об этом нельзя, иначе разбираться
    # придётся по пустому списку правок.
    if reason in ("no git", "no repo"):
        logger.warning(
            "история версий песочницы недоступна",
            extra={"component": "workspace", "failure_code": "history_unavailable"},
        )


async def persist_all_artifacts(
    file_service,
    user_id: Any,
    metadata: dict[str, Any],
    job_id: str,
    engine_env: dict[str, Any] | None = None,
    execution_result: dict[str, Any] | None = None,
    user_text: str = "",
) -> tuple[str | None, dict[str, Any]]:
    """Забрать файлы из песочницы, снять её состояние и сохранить артефакты прогона.

    ⚠️ Принимает ОКРУЖЕНИЕ и РЕЗУЛЬТАТ целиком, а не разобранные поля: разбор здесь — это
    одна строка, а у вызывающего он стоил бы четырёх, и функция воркера, давно вышедшая за
    потолок храповика, росла бы ради удобства подписи.

    Файлы песочницы дописываются в `_pending_artifacts` — тот же список, которым уже
    пользуется мульти-интент. Дальше их персистит существующий мост.
    """
    from service.infrastructure.agents_client.agent_file_bridge import persist_generated_artifacts

    workspace_ref = (engine_env or {}).get("workspace_ref")
    await _persist_document_artifacts(file_service, user_id, metadata, workspace_ref)
    inventory = _collectable_workspace_inventory(
        (execution_result or {}).get("workspace_artifacts")
    )
    if workspace_ref and inventory:
        from service.infrastructure.workspace_client import collect_artifacts

        files = await collect_artifacts(workspace_ref, inventory)
        if files:
            pending = list(metadata.get("_pending_artifacts") or [])
            metadata["_pending_artifacts"] = pending + files

    # Снимок истории — ЗДЕСЬ, а не у вызывающего: это единственное место, которое уже
    # знает про песочницу и исполняется ровно раз на ход, после того как файлы забраны.
    await snapshot_workspace(engine_env, user_text)

    return await persist_generated_artifacts(
        file_service=file_service, user_id=user_id, metadata=metadata, job_id=job_id
    )
