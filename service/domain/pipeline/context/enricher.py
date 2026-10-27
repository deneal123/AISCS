"""Context enrichment helpers for agent pipeline."""

from __future__ import annotations

from typing import Any


async def load_memory_parts(
    user_id: int | str | None, logger, query: str | None = None
) -> tuple[str, str]:
    """Два слоя памяти ОТДЕЛЬНО: ``(факты из Postgres, семантический recall из MemOS)``.

    Раздельно — потому что у них разный бюджет и разный приоритет: факты о пользователе
    мелкие и почти неприкосновенные, а recall может быть объёмным и режется первым.
    В САЙДКАРЕ память не читается: её собирает backend (у него MemOS и Postgres) и
    кладёт в тело запроса полем ``memory_parts`` — см. ``resolve_memory_parts`` ниже,
    контракт «prefer passed-in». Пустой ответ здесь означает «backend памяти не дал».

    Раньше тут стоял фолбэк с импортом ``service.services.analytics…MemoryService``.
    Этого модуля в сайдкаре нет, импорт падал под ``except``, и функция всё равно
    возвращала пустоту — мёртвый код, выглядевший рабочим запасным путём.
    """
    return "", ""


async def resolve_memory_parts(
    memory_parts: tuple[str, str] | None,
    *,
    user_id: int | str | None,
    memory_enabled: bool,
    query: str | None,
    logger,
) -> tuple[str, str]:
    """Память для контекста: готовые данные из запроса ЛИБО собственный fetch (fallback).

    Единый контракт «prefer passed-in, else fetch» для выноса agents в сайдкар
    (Фаза 0b, stateless). Если бэкенд уже собрал память и передал её в ``memory_parts``
    — возвращаем как есть (сайдкар не знает про MemOS backend'а). ``None`` → грузим сами
    (тесты/прямые вызовы; поведение как раньше). Гейт ``memory_enabled`` применяется
    ТОЛЬКО на пути собственного fetch — если данные пришли готовыми, их гейтит бэкенд.
    """
    if memory_parts is not None:
        return memory_parts
    if not memory_enabled:
        return "", ""
    return await load_memory_parts(user_id, logger, query=query)


async def resolve_history(
    history_messages: list[dict] | None,
    session: Any | None,
    logger,
    *,
    compact_summary: str,
    history_limit: int,
    summary_keep_recent: int,
) -> list[dict]:
    """История диалога для контекста: готовые реплики из запроса ЛИБО загрузка из сессии.

    Контракт «prefer passed-in, else fetch» для выноса agents в сайдкар (Фаза 0b,
    stateless). Если бэкенд собрал историю (гидрировал сессию из PG, применил лимит) и
    передал её в ``history_messages`` — используем как есть (сайдкар не имеет доступа к
    PG backend'а). ``None`` → грузим из сессии сами (fallback: тесты/прямые вызовы,
    поведение как раньше).

    При наличии ``compact_summary`` живая история обрезается до ``summary_keep_recent``
    (компактизация как в Claude Code: старое уже ушло в резюме), иначе — до
    ``history_limit``. Лимит считается ТОЛЬКО на пути собственной загрузки — если
    история пришла готовой, лимит уже применён бэкендом.
    """
    if history_messages is not None:
        return history_messages
    limit = summary_keep_recent if compact_summary else history_limit
    return await load_history_items(session, logger, limit_messages=limit)


async def load_history_items(session: Any | None, logger, *, limit_messages: int = 8) -> list[dict]:
    """Сырые реплики диалога из сессии: ``[{role, content}]``, только валидные роли.

    Вынесено из ``build_history_messages``, чтобы ассемблер контекста мог получить
    историю ДО обрезки и посчитать её в общем бюджете наравне с остальными секциями.
    """
    if session is None or limit_messages <= 0:
        return []
    get_items = getattr(session, "get_items", None)
    if not callable(get_items):
        return []
    try:
        try:
            items = await get_items(limit=limit_messages)
        except TypeError:
            items = await get_items()
    except Exception:
        logger.debug("session history unavailable", extra={"failure_code": "unavailable"})
        return []
    if not isinstance(items, list) or not items:
        return []

    valid: list[dict] = []
    for item in items[-limit_messages:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        valid.append({"role": role, "content": content})
    return valid


# schedule_memory_extraction (fire-and-forget create_task) удалён: у него не было
# НИ ОДНОГО вызова, а сам приём — footgun под celery loop-per-task (несохранённая
# ссылка на задачу + закрытие loop сразу после ответа → факт молча терялся). Живой,
# durable путь извлечения памяти — awaited MemoryService().extract_and_save_facts(...)
# в воркере (chat_worker_tasks._extract_and_persist_memory), с тарификацией usage.
# Нужна фоновая экстракция вне воркера — оформляй celery-таском, а не create_task.
