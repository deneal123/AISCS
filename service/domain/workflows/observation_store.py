"""Где живут наблюдения за повторяющимися сценариями треда.

⚠️ ХРАНЕНИЕ ОТДЕЛЬНО ОТ ПРАВИЛА (`observation.py`). Правило «повтор или совпадение»
проверяется без сети и потому проверяется вообще; здесь только чтение и запись.

Fail-open по всему пути: Redis не сконфигурен или лёг — наблюдений просто нет, и
платформа работает ровно как раньше. Наблюдение это НАБЛЮДЕНИЕ, а не данные пользователя:
терять его не жалко, а ронять из-за него ход нельзя.

🔴 СРОК ЖИЗНИ ОБЯЗАТЕЛЕН. Ключ на тред без срока — это утечка: тредов у платформы столько
же, сколько разговоров, и ни один из них не удаляет за собой ключ наблюдений.
"""

from __future__ import annotations

import json
import logging

from .observation import MAX_HISTORY, Chain, observe

logger = logging.getLogger(__name__)

# Неделя. Сценарий, не повторившийся за неделю, сценарием и не был; а держать наблюдения
# дольше треда, который их породил, незачем.
TTL_SEC = 7 * 24 * 3600


def _key(thread_id: str) -> str:
    return f"agents:{thread_id}:chains"


async def load(thread_id: str | None) -> list[Chain]:
    """История цепочек треда. Пусто — наблюдений нет либо хранилище недоступно."""
    from service.shared.redis_client import get_redis

    client = get_redis()
    if client is None or not thread_id:
        return []
    try:
        raw = await client.get(_key(str(thread_id)))
    except Exception:  # noqa: BLE001 — без наблюдений платформа работает как раньше
        logger.debug("workflow observations unavailable", extra={"failure_code": "unavailable"})
        return []
    return _decode(raw)


async def record(thread_id: str | None, chain: Chain) -> list[Chain]:
    """Дописать наблюдение и вернуть обновлённую историю.

    ⚠️ Возвращаем историю, а не `None`: вызывающему она нужна СРАЗУ — решение о
    предложении принимается по ней в этом же ходу, и второе чтение из Redis показало бы
    ровно то, что мы только что записали, но стоило бы лишнего обращения.
    """
    from service.shared.redis_client import get_redis

    history = observe(await load(thread_id), chain)
    client = get_redis()
    if client is None or not thread_id:
        return history
    try:
        payload = json.dumps(
            [
                {"steps": list(item.steps), "from_workflow": item.from_workflow}
                for item in history[-MAX_HISTORY:]
            ],
            ensure_ascii=False,
        )
        await client.setex(_key(str(thread_id)), TTL_SEC, payload)
    except Exception:  # noqa: BLE001
        logger.debug("workflow observations unavailable", extra={"failure_code": "unavailable"})
    return history


def _decode(raw) -> list[Chain]:
    """Разобрать хранимое. ⚠️ Мусор — ПУСТАЯ история, а не исключение: запись мог оставить
    код другой версии, и падать из-за наблюдений нельзя."""
    if not raw:
        return []
    try:
        data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    out: list[Chain] = []
    for item in data:
        steps = (item or {}).get("steps") if isinstance(item, dict) else None
        if isinstance(steps, list) and steps:
            out.append(
                Chain(
                    steps=tuple(str(s) for s in steps),
                    from_workflow=bool(item.get("from_workflow")),
                )
            )
    return out[-MAX_HISTORY:]
