"""Сбор данных для прогона агента — BACKEND-половина шва Фазы 0b.

Сайдкар stateless: историю треда, память и резюме он получает готовыми в теле ``/run``.
Достаёт их отсюда воркер — из PG, MemOS и Redis, то есть из хранилищ, к которым доступ
есть только у backend.

Раньше эти функции лежали в ``domain/pipeline`` — внутри дерева, которое уехало в
сайдкар. Там они выглядели инородно и создавали цикл: ``load_memory_parts`` из «домена»
импортировал ``MemoryService`` из backend-аналитики. Разрезано по владению: достаёт
backend, использует домен.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from service.infrastructure.agents_client.ports import resolve_user_uuid
from service.services.chat.infrastructure.document_kinds import (
    _document_among,
    message_has_non_tabular_attachment,
)
from service.settings import config
from service.shared.tabular_shape import FORMAT_IS_TABLE, HEAD_BYTES, looks_tabular

logger = logging.getLogger(__name__)

DUCKDB_NATIVE_EXTENSIONS = (
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".pqt",
    ".json",
    ".jsonl",
    ".ndjson",
    ".xlsx",
)
CONVERT_EXTENSIONS = (".xls", ".ods", ".xlsm", ".fods")

TABULAR_EXTENSIONS = (*DUCKDB_NATIVE_EXTENSIONS, *CONVERT_EXTENSIONS)

MAX_FILES = 6


def _ext(name: str) -> str:
    return Path(str(name or "")).suffix.lower()


class PseudoSession:
    """In-memory буфер истории на время подготовки запроса.

    Копия доменной сессии без её телеметрии: здесь объект живёт секунды и в сайдкар не
    едет, поэтому мерить его длину незачем.
    """

    def __init__(
        self, session_id: str, ttl_seconds: int | None = None, max_items: int | None = None
    ):
        self.session_id = session_id
        self._items: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._max_items = max_items

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            items = list(self._items)

        if self._ttl is not None:
            cutoff = datetime.now(UTC).timestamp() - self._ttl
            items = [
                it for it in items if float(it.get("ts", datetime.now(UTC).timestamp())) >= cutoff
            ]

        if limit is not None:
            items = items[-limit:]
        return items

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._items.extend(items)
            if self._max_items is not None and len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]

    async def pop_item(self) -> dict[str, Any] | None:
        async with self._lock:
            if not self._items:
                return None
            item = self._items.pop()

        return item

    async def clear_session(self) -> None:
        async with self._lock:
            self._items.clear()


def create_session(session_id: str) -> PseudoSession:
    """Сессия для СБОРА истории на стороне backend.

    Живёт ровно на время подготовки запроса: воркер наполняет её из БД и вынимает
    ``history_messages`` для тела ``/run``. В сайдкар она НЕ едет (Фаза 0b: историю несут
    данные, а не объект), поэтому копия здесь — не дубль состояния, а локальный буфер.
    """
    return PseudoSession(session_id=session_id)


def _summary_key(cache_prefix: str, session_id: str) -> str:
    """Ключ кэша резюме. Формат ДОЛЖЕН совпадать с тем, которым пишет сайдкар: пишет
    компактизацию он, читает воркер — разъедутся, и резюме молча перестанет находиться,
    а контекст будет собираться без него (дороже и хуже, но без единой ошибки)."""
    prefix = (cache_prefix or "gpthub").rstrip(":")
    return f"{prefix}:agents:summary:{session_id}"


async def load_memory_parts(
    user_id: int | str | None, logger, query: str | None = None
) -> tuple[str, str]:
    """Два слоя памяти ОТДЕЛЬНО: ``(факты из Postgres, семантический recall из MemOS)``.

    Раздельно — потому что у них разный бюджет и разный приоритет: факты о пользователе
    мелкие и почти неприкосновенные, а recall может быть объёмным и режется первым.
    Оба слоя fail-open. Recall запрашивается только при непустом ``query`` (иначе не
    шумим и не тратим вызов).
    """
    if not user_id:
        return "", ""

    try:
        from service.services.analytics.application.memory_service import MemoryService

        mem_svc = MemoryService()
        # Запрос нужен для ОТБОРА фактов: без него в промпт уезжают просто самые
        # свежие, и вопрос про Python получает знак зодиака (замер на живой базе).
        facts_ctx = await mem_svc.get_memory_context(str(user_id), query=query or "")
        recall_ctx = ""
        if query and str(query).strip():
            recall_ctx = await mem_svc.recall_semantic(str(user_id), str(query))
        return facts_ctx or "", recall_ctx or ""
    except Exception:
        logger.debug("Memory context loading failed", exc_info=True)
        return "", ""


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
        logger.debug("Session history (messages) loading failed", exc_info=True)
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


async def read_cached_summary(session_id: str, redis_client, cache_prefix: str = "gpthub") -> str:
    """Дешёвое чтение готового саммери из Redis (без LLM). Пусто, если компактизации
    ещё не было. Используется процессором per-turn для обрезки живого контекста."""
    if not session_id or redis_client is None:
        return ""
    try:
        raw = await redis_client.get(_summary_key(cache_prefix, session_id))
        if not raw:
            return ""
        cached = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        return str(cached.get("summary") or "")
    except Exception:
        logger.debug("Summary cache read failed", exc_info=True)
        return ""


# --------------------------------------------------------- компактизация треда --
# Сжатие истории живёт у backend, потому что кэш резюме — в ЕГО Redis, а сама сборка
# истории идёт из ЕГО базы. LLM-часть при этом делегируется сайдкару: суммаризатор
# передаётся аргументом, и backend подставляет вызов через шлюз (см. compact_context).


async def gateway_summarizer(messages: list[dict], *, max_tokens: int) -> str:
    """Суммаризатор через LLM-шлюз сайдкара — backend провайдеров не знает."""
    from service.infrastructure.llm_gateway import chat_completion
    from service.settings import config as _cfg

    rendered = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content', '')).strip()}" for m in messages
    )
    result = await chat_completion(
        _cfg,
        messages=[
            {
                "role": "system",
                "content": (
                    "Сожми диалог в краткое резюме: факты, решения, договорённости. "
                    "Без вводных фраз, только суть."
                ),
            },
            {"role": "user", "content": rendered},
        ],
        model=str(getattr(_cfg.agents, "summary_model", "") or "openai:gpt-4o-mini"),
        max_tokens=max_tokens,
    )
    return result[0] if result else ""


async def get_or_build_history_summary(
    *,
    items: list[dict],
    session_id: str,
    redis_client,
    cache_prefix: str = "gpthub",
    trigger_messages: int = 12,
    keep_recent: int = 6,
    max_tokens: int = 400,
    summarizer=None,
) -> str:
    """Вернуть (из кэша или построив) резюме старой части истории.

    Возвращает "" если суммаризация не нужна/недоступна. Кэш инвалидируется, когда
    появились новые сообщения сверх ранее покрытых (covered_upto).
    """
    if not session_id or redis_client is None or not items:
        return ""
    if len(items) <= trigger_messages:
        return ""

    older = items[: max(0, len(items) - keep_recent)]
    covered = len(older)
    if covered <= 0:
        return ""

    key = _summary_key(cache_prefix, session_id)
    try:
        raw = await redis_client.get(key)
        if raw:
            cached = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            if int(cached.get("covered_upto", 0)) >= covered and cached.get("summary"):
                return str(cached["summary"])
    except Exception:
        logger.debug("Summary cache read failed", exc_info=True)

    try:
        # Суммаризатор ОБЯЗАН быть подан: backend провайдеров не знает, дефолта здесь
        # нет и быть не может — молчаливый «дефолт» означал бы попытку звонить самому.
        if summarizer is None:
            logger.error("компактизация без суммаризатора: пропускаем")
            return ""
        build = summarizer
        summary = await build(older, max_tokens=max_tokens)
    except Exception:
        logger.debug("History summarization failed", exc_info=True)
        return ""

    summary = str(summary or "").strip()
    if not summary:
        return ""

    try:
        payload = json.dumps(
            {"summary": summary, "covered_upto": covered, "history_len": len(items)},
            ensure_ascii=False,
        )
        await redis_client.set(key, payload)
    except Exception:
        logger.debug("Summary cache write failed", exc_info=True)

    return summary


# ------------------------------------------------- табличные файлы пользователя --
# Ещё одна backend-половина шва (Фаза 0b.4): ссылки собирает тот, у кого есть PG и
# MinIO, а скачивает по ним сайдкар. Байты по сети не гоняем — файл может весить
# десятки мегабайт, а инструмент вызывается редко.


# Тот же срок жизни, что у текста вложения в треде (``_recall_or_persist_thread_file``):
# состав файлов диалога и их содержимое обязаны истекать вместе, иначе останется
# ссылка на таблицу, текст которой уже забыт.
_THREAD_FILES_TTL_SEC = 7200


async def _recall_or_persist_thread_tabular(
    redis_client, thread_id: str, file_ids, *, has_new_file: bool = False
) -> list[str]:
    """Какие файлы считать «приложенными в этом диалоге» — по треду, как и их текст.

    Близнец ``_recall_or_persist_thread_file`` для ИДЕНТИФИКАТОРОВ. Нужен, потому что
    ``profile.user_file`` не знает про треды: выборка по ``user_id`` возвращает всё
    загруженное когда-либо, и «в сообщении есть таблица» становилось вечным свойством
    аккаунта (разбор — в ``list_user_tabular_file_links``).

    Семантика как у текста: новый файл → набор треда РАВЕН файлам этого сообщения (в том
    числе пустым: приложили PDF — значит таблиц больше нет); нового нет → отдаём
    запомненный, чтобы follow-up не потерял таблицу. Fail-open по Redis.
    """
    current = [str(f) for f in (file_ids or []) if f]
    if redis_client is None or not thread_id:
        return current
    key = f"chat:{thread_id}:file_ids"
    try:
        # redis_client воркера СИНХРОННЫЙ (redis.Redis) — блокирующие вызовы уводим в
        # тред: `await` на sync-результате молча ломал бы фичу (так уже было с текстом
        # вложения — «файл живёт в треде» не работал, а выглядел рабочим).
        if has_new_file:
            if current:
                await asyncio.to_thread(
                    redis_client.set, key, json.dumps(current), ex=_THREAD_FILES_TTL_SEC
                )
            else:
                await asyncio.to_thread(redis_client.delete, key)
            return current
        prior = await asyncio.to_thread(redis_client.get, key)
        if prior:
            if isinstance(prior, bytes):
                prior = prior.decode("utf-8", "ignore")
            loaded = json.loads(prior)
            if isinstance(loaded, list):
                return [str(x) for x in loaded]
    except Exception:
        logger.debug("thread tabular ids recall/persist failed", exc_info=True)
    return current


async def _forget_thread_files(redis_client, thread_id: str) -> None:
    """Забыть набор файлов треда: он указывает на записи, которых в базе нет.

    ⚠️ Best-effort и БЕЗ падения хода: Redis тут — кэш, а не источник истины. Не смогли
    стереть — следующий ход попробует снова, это лучше, чем уронить ответ человеку.
    """
    if redis_client is None or not thread_id:
        return
    try:
        await asyncio.to_thread(redis_client.delete, f"chat:{thread_id}:file_ids")
        logger.warning(
            "память треда %s о файлах СТЁРТА: все её идентификаторы мертвы. Следующий ход "
            "возьмёт файлы заново из сообщения",
            thread_id,
        )
    except Exception:
        logger.debug("не удалось стереть память треда о файлах", exc_info=True)


async def collect_thread_files(
    redis_client, thread_id: str, user_id, session_data, *, has_new_file: bool = False
) -> tuple[list[dict] | None, list[dict]]:
    """Файлы ЭТОГО диалога ссылками: ``(таблицы для analyze_data, всё для песочницы)``.

    ⚠️ ТОЛЬКО файлы текущего диалога. Без ограничения выборка шла по всему аккаунту, и
    любой давний .csv/.json делал признак «в сообщении есть таблица» вечно истинным —
    движок выбрасывал текст нетабличного вложения из промпта (живой инцидент: PDF-ТЗ на
    16 076 символов, промпт 1 606 токенов, агент переспросил «что нужно сделать»).

    🔴 ДВА СПИСКА, А НЕ ОДИН. В песочницу раньше импортировался ТАБЛИЧНЫЙ список, то есть
    рабочее место человека содержало только то, что имеет смысл в SQL: приложил `.docx` —
    и файловым инструментам открывать нечего, хотя файл «приложен». Отбор по форме — про
    `analyze_data`, а песочница про работу с файлами, и совпадать эти два круга не обязаны.

    Best-effort: не смогли собрать → ``(None, [])``, прогон идёт без ``analyze_data``.
    """
    try:
        thread_file_ids = await _recall_or_persist_thread_tabular(
            redis_client, thread_id, (session_data or {}).get("file_ids"), has_new_file=has_new_file
        )
        dialog = await list_user_dialog_file_links(user_id, file_ids=thread_file_ids)
        # 🔴 МЁРТВАЯ ПАМЯТЬ ТРЕДА ЧИСТИТСЯ, А НЕ ПЕРЕЖИВАЕТ СЛЕДУЮЩИЕ ХОДЫ. Набор
        # идентификаторов лежит в Redis два часа и с БД не сверяется; удалённая запись делает
        # его вечным источником пустоты — каждый следующий ход просит те же мёртвые id,
        # получает ноль ссылок и оставляет песочницу пустой. Замерено живьём: человек дважды
        # получил «в рабочем каталоге отсутствуют файлы» при приложенных файлах.
        #
        # ⚠️ Чистим ТОЛЬКО когда просили и не нашли НИ ОДНОГО: частичная потеря может быть
        # законной (файл удалён, остальные на месте), и стирать по ней весь набор значило бы
        # терять живые файлы. Сам ход при этом не роняем — пустой каталог честнее обрыва.
        if thread_file_ids and not dialog:
            await _forget_thread_files(redis_client, thread_id)
        return (
            await list_user_tabular_file_links(user_id, file_ids=thread_file_ids),
            dialog,
        )
    except Exception:
        logger.debug("ссылки на файлы диалога собрать не удалось", exc_info=True)
        return None, []


async def collect_thread_tabular_files(
    redis_client, thread_id: str, user_id, session_data, *, has_new_file: bool = False
) -> list[dict] | None:
    """Только табличная половина ``collect_thread_files`` (совместимость вызовов)."""
    tabular, _ = await collect_thread_files(
        redis_client, thread_id, user_id, session_data, has_new_file=has_new_file
    )
    return tabular


async def read_thread_repo_graphs(redis_client, thread_id: str | None) -> list[str]:
    """graph_id репозиториев, разобранных В ЭТОМ ТРЕДЕ (привязаны на аплоаде).

    Нужно инструменту search_knowledge_graph: код репозитория лежит в ОТДЕЛЬНОМ графе
    `repo-{uuid}`, а не в личном графе документов юзера. Без этой связи агент искал код в
    графе PDF-документов и не находил (живой инцидент: 9 бесплодных вызовов, 9880 кр).
    Best-effort: Redis лёг / ключа нет → пусто, инструмент работает по личному графу.
    """
    if redis_client is None or not thread_id:
        return []
    try:
        # Список (lpush+ltrim на аплоаде): последние N графов треда, новейший первым.
        raw = await asyncio.to_thread(redis_client.lrange, f"chat:{thread_id}:repo_graphs", 0, -1)
    except Exception:
        logger.debug("не удалось прочитать графы репозиториев треда", exc_info=True)
        return []
    out = []
    for item in raw or []:
        out.append(item.decode("utf-8", "ignore") if isinstance(item, bytes) else str(item))
    return out


async def collect_message_extras(
    redis_client,
    thread_id: str | None,
    attachments,
    *,
    detach_files: bool = False,
    dialog_files: list[dict] | None = None,
) -> tuple[str | None, bool, list[str]]:
    """Сигналы для http-прогона: (референс-картинка, есть ли документ, графы репо треда).

    Обёртка держит воркер компактным. Референс — из истории треда (БД),
    документ-рядом-с-таблицей — из `attachments` сообщения, графы репо — из Redis треда.

    ⚠️ `detach_files` (открепил крестиком) стирает и графы репо треда: иначе открепление
    убирало карту репозитория из промпта, но `search_knowledge_graph` продолжал искать в
    его графе — код откреплённого репо утекал в ответ. Стирать заодно с last_file/file_ids.
    """
    reference = await recall_last_thread_image_url(thread_id)
    if detach_files and redis_client is not None and thread_id:
        try:
            await asyncio.to_thread(redis_client.delete, f"chat:{thread_id}:repo_graphs")
        except Exception:
            logger.debug(
                "не удалось стереть графы репозиториев треда при откреплении", exc_info=True
            )
        repo_graphs: list[str] = []
    else:
        repo_graphs = await read_thread_repo_graphs(redis_client, thread_id)
    # 🔴 ПРИЗНАК НЕ ДОЛЖЕН ЗАВИСЕТЬ ОТ ДОБРОСОВЕСТНОСТИ КЛИЕНТА. Он читался ТОЛЬКО из
    # `attachments[].kind`, который проставляет фронт. Замерено: сообщение с `file_ids`, но
    # без `attachments` (сторонний клиент, наш же HTTP-путь, повтор запроса) — таблица и
    # документ приложены оба, а текст документа выброшен из промпта как «табличный», и
    # агент ответил «уточните, где данные о планах». Имена файлов диалога backend знает
    # сам, и по ним видно, что рядом с таблицей лежит документ.
    has_document = message_has_non_tabular_attachment(attachments) or _document_among(dialog_files)
    return reference, has_document, repo_graphs


async def recall_last_thread_image_url(thread_id: str | None) -> str | None:
    """Презайнед-ссылка на ПОСЛЕДНЮЮ картинку треда — для image-to-image.

    Картинка живёт в ``generated_files`` последнего ассистентского сообщения; отдаём по
    ней СВЕЖУЮ презайнед-ссылку — та, что в metadata, протухает через час. ``None`` —
    картинок нет либо собрать не удалось (best-effort).

    ⚠️ Наличие картинки НЕ означает, что запрос — правка: «нарисуй собаку» после «нарисуй
    кота» рисует заново. Решает субагент по тексту; здесь мы лишь ДАЁМ ссылку.
    """
    from sqlalchemy import text

    from service.services.chat.infrastructure.chat_worker.factory import (
        ChatWorkerDependencyFactory,
        build_file_service,
    )

    if not thread_id:
        return None
    pg = ChatWorkerDependencyFactory().create_pg_connector(config)
    try:
        async with pg.get_session_context() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT m."metadata"
                        FROM profile.chat_messages m
                        JOIN profile.chat_threads t ON t.id = m.thread_id
                        WHERE t.thread_id = :thread_id
                          AND m."metadata"->'generated_files' @> '[{"kind": "image"}]'
                        ORDER BY m.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"thread_id": thread_id},
                )
            ).fetchone()
    except Exception:
        logger.warning("не удалось прочитать последнюю картинку треда", exc_info=True)
        return None
    if not row:
        return None

    metadata = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    files = (metadata or {}).get("generated_files") or []
    key = next(
        (f.get("file_key") for f in files if isinstance(f, dict) and f.get("kind") == "image"),
        None,
    )
    if not key:
        return None
    file_service = build_file_service(config, pg)
    try:
        return await file_service.get_presigned_url_by_key(file_key=key)
    except Exception:
        logger.warning("не удалось презайнить последнюю картинку треда", exc_info=True)
        return None


async def list_user_tabular_file_links(
    user_id: str | None, *, file_ids: Sequence[str] | None = None
) -> list[dict]:
    """Табличные файлы пользователя → ``[{name, url}]`` с ПРЕЗАЙНЕД-ссылками (без байтов).

    Воркер зовёт это ПЕРЕД прогоном и кладёт ссылки в тело ``/run``: сайдкар скачает файлы
    сам, не имея PG/MinIO. Только для HTTP-движка — in-process инструмент сходит в
    хранилище напрямую.

    ⚠️ ``file_ids`` — ФАЙЛЫ ЭТОГО ДИАЛОГА, а не всего аккаунта. Живой инцидент: два
    ``.json`` двенадцатидневной давности из ЧУЖИХ тредов делали список непустым, движок
    считал, что в сообщении таблица, выбрасывал текст приложенного PDF и переспрашивал
    «что нужно сделать». Пустой список значит «таблиц нет», а не «фильтра нет».
    """
    rows, file_service = await _dialog_file_rows(user_id, file_ids)
    candidates = [r for r in rows if _ext(getattr(r, "file_name", "")) in TABULAR_EXTENSIONS]
    if not candidates:
        return []

    out: list[dict] = []
    for row in candidates[:MAX_FILES]:
        key = getattr(row, "file_name", "")
        if not await _file_is_tabular(file_service, key):
            continue
        if url := await _presign(file_service, key):
            # Имя несёт РАСШИРЕНИЕ (по нему сайдкар решает про конвертацию и формат).
            out.append({"name": key, "url": url})
    return out


async def list_user_dialog_file_links(
    user_id: str | None, *, file_ids: Sequence[str] | None = None
) -> list[dict]:
    """ВСЕ файлы диалога ссылками — то, что кладётся в песочницу.

    🔴 Отличие от табличного списка принципиальное: там отбор по ФОРМЕ (что имеет смысл
    отдать в SQL), здесь — рабочее место человека. Пока импорт шёл по табличному списку,
    приложенный `.docx` в песочнице не появлялся вовсе, и файловым инструментам нечего
    было открывать — при том что файл «приложен» и человек его видит в сообщении.
    """
    rows, file_service = await _dialog_file_rows(user_id, file_ids)
    out: list[dict] = []
    taken: set[str] = set()
    for row in rows[:MAX_FILES]:
        key = getattr(row, "file_name", "")
        if url := await _presign(file_service, key):
            out.append({"name": _workspace_name(row, taken), "url": url})
    return out


def _workspace_name(row, taken: set[str]) -> str:
    """Как файл называется В РАБОЧЕМ КАТАЛОГЕ — так, как его прислал человек.

    🔴 Ключ хранилища обезличен намеренно, и до появления рабочего каталога это никого не
    трогало: наружу файлы отдавались ссылкой. Теперь они ВИДНЫ — и в дереве панели, и у
    агента в `ws_list`. Живой прогон показал `uploads/CHAT/123f5c3b….json` вместо
    `рассылка.json`: по такому имени не понять, что это за файл, ни человеку, ни модели.

    ⚠️ Берём ТОЛЬКО базовое имя: исходное имя приходит от пользователя, а `../../etc/x`
    в нём — обычное дело. Сайдкар отвергнет такой путь своим `safe_path`, но тогда файл
    просто не доедет; чинить это на своей стороне честнее, чем ловить отказ чужого.

    ⚠️ Столкновения имён разводим суффиксом: в одном диалоге легко оказаться двум
    `отчёт.xlsx`, а второй молча затёр бы первый.
    """
    original = str(getattr(row, "original_name", "") or "").strip()
    key = str(getattr(row, "file_name", "") or "")
    name = Path(original.replace("\\", "/")).name if original else Path(key).name
    name = name.strip() or Path(key).name or "file"
    if name not in taken:
        taken.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    for index in range(2, MAX_FILES + 2):
        candidate = f"{stem} ({index}){suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    return name


async def _presign(file_service, file_key: str) -> str | None:
    try:
        return await file_service.get_presigned_url_by_key(file_key=file_key)
    except Exception:
        logger.debug("презайнед-ссылка на %s не получена", file_key, exc_info=True)
        return None


async def _dialog_file_rows(user_id: str | None, file_ids: Sequence[str] | None):
    """Записи ``UserFile`` ЭТОГО диалога + файл-сервис на том же соединении.

    ⚠️ ``file_ids`` — ФАЙЛЫ ЭТОГО ДИАЛОГА, а не всего аккаунта. Живой инцидент: два
    ``.json`` двенадцатидневной давности из ЧУЖИХ тредов делали список непустым, движок
    считал, что в сообщении таблица, выбрасывал текст приложенного PDF и переспрашивал
    «что нужно сделать». Пустой список значит «файлов нет», а не «фильтра нет».
    """
    user_uuid = resolve_user_uuid(user_id, anonymous_fallback=False)
    if user_uuid is None:
        return [], None
    # None — фильтра нет (in-process/старый вызов, поведение прежнее); пустой список —
    # в этом диалоге файлов нет, и ходить в БД не за чем.
    if file_ids is not None and not file_ids:
        return [], None
    wanted = {str(fid) for fid in (file_ids or [])} or None

    from sqlalchemy import select

    from service.models.db.db_models import UserFile
    from service.models.key_value import ServiceType
    from service.services.chat.infrastructure.chat_worker.factory import (
        ChatWorkerDependencyFactory,
        build_file_service,
    )

    pg = ChatWorkerDependencyFactory().create_pg_connector(config)
    try:
        async with pg.get_session_context() as session:
            result = await session.execute(select(UserFile).where(UserFile.user_id == user_uuid))
            rows = list(result.scalars().all())
    except Exception:
        logger.warning("не удалось прочитать файлы пользователя (ссылки)", exc_info=True)
        return [], None

    scoped = [
        r
        for r in rows
        if getattr(r, "type", None) == ServiceType.CHAT
        and (wanted is None or str(getattr(r, "id", "")) in wanted)
    ]
    _report_missing_rows(wanted, len(scoped))
    return scoped, build_file_service(config, pg)


def _report_missing_rows(wanted: set[str] | None, found: int) -> None:
    """Назвать расхождение «просили N файлов — нашли M».

    🔴 ЗАПРОСИЛИ ФАЙЛЫ И НЕ НАШЛИ НИ ОДНОГО — ЭТО ПОЛОМКА, А НЕ «ФАЙЛОВ НЕТ». Набор
    идентификаторов помнится в Redis два часа и с БД НЕ СВЕРЯЕТСЯ, поэтому удалённая запись
    превращает список в пустой — молча, и дальше по цепочке пустота выглядит штатной:
    `import_files(ref, [])` не кладёт ничего, песочница остаётся пустой, а модель честно
    сообщает человеку «файлы не загрузились».

    Замерено на живом стеке по отчёту человека: `chat:<тред>:file_ids` = один идентификатор,
    записи с ним в `profile.user_file` НЕТ ВОВСЕ; песочница создана, в её истории только
    «песочница создана», записи «файлы пользователя» нет. Человек получил «в рабочем каталоге
    отсутствуют файлы для анализа» при приложенных файлах — и это был ЕДИНСТВЕННЫЙ след.

    ⚠️ Числа в сообщении несущие: «потеряно всё» и «потеряна часть» — разные поломки с
    разными причинами, и лечатся они по-разному.

    ⚠️ Отдельной функцией, а не ветками внутри сборщика: правило проверяется тестом напрямую,
    без подмены БД и файлового сервиса.
    """
    if not wanted:
        return
    if not found:
        logger.warning(
            "файлы диалога не найдены В БАЗЕ: запрошено %d идентификаторов (%s), найдено 0 — "
            "песочница останется ПУСТОЙ, и агент скажет человеку, что файлов нет. Обычно это "
            "значит, что записи удалены, а память треда о них ещё жива",
            len(wanted),
            ", ".join(sorted(wanted)[:5]),
        )
    elif found < len(wanted):
        logger.warning(
            "часть файлов диалога не найдена в базе: запрошено %d, найдено %d — ответ будет "
            "построен по НЕПОЛНОМУ набору",
            len(wanted),
            found,
        )


async def _file_is_tabular(file_service, file_key: str) -> bool:
    """Таблица ли это ПО СОДЕРЖИМОМУ. Расширение только сужает круг кандидатов.

    🔴 `.json` бывает и таблицей, и деревом настроек; расширение отвечало «таблица»
    всегда, и просьба «прочитай десятую строку» уходила в SQL, где строк нет. Форму
    решает голова файла — см. ``shared.tabular_shape``.
    """
    if _ext(file_key) in FORMAT_IS_TABLE:
        return True
    try:
        head = await file_service.get_file_head_by_key(file_key=file_key, max_bytes=HEAD_BYTES)
    except Exception:
        logger.debug("голова файла %s не прочиталась", file_key, exc_info=True)
        head = None
    return looks_tabular(file_key, head)
