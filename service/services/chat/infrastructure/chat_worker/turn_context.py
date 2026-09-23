"""Что агент УВИДИТ на этом ходу: вложения, память, история, файлы диалога, окружение.

Отдельный узел, а не часть большой функции воркера: у него своя причина меняться — меняются
ИСТОЧНИКИ (хранилище файлов, MemOS, история треда, песочница), а не то, как исполняется
прогон и как он тарифицируется. Вынесено из `process_agent_message_async`, которая давно за
потолком храповика; кусок самостоятелен и ничего из её локальных переменных не требует.

⚠️ ПОРЯДОК ЗДЕСЬ НЕСУЩИЙ, и каждый шаг оплачен своим инцидентом:
* признак «в этом сообщении новый файл» считается ПЕРВЫМ — от него зависит, воскрешать ли
  прежнее вложение и стирать ли память треда о файлах;
* текст вложения восстанавливается ДО записи в память треда, иначе в неё уедет пустота;
* саммери читается ДО истории: при непустом саммери у истории другой лимит.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from service.infrastructure.agents_client.engine_factory import uses_http_engine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnContext:
    """Собранное окружение хода. Пустые значения — норма: их просто не будет в промпте."""

    file_context: str
    has_new_file: bool
    memory_parts: tuple[str, str]
    history_messages: list[dict]
    compact_summary: str
    persona_switched: bool
    tabular_files: list[dict] | None = None
    reference_image_url: str | None = None
    has_non_tabular_attachment: bool = False
    repo_graph_ids: list[str] = field(default_factory=list)
    engine_env: dict[str, Any] = field(default_factory=dict)


def message_has_new_file(attachments: Any, session_data: dict | None) -> bool:
    """Приложен ли файл ИМЕННО В ЭТОМ сообщении.

    🔴 От признака зависят три разные вещи, поэтому он считается один раз и здесь: воскрешать
    ли прежнее вложение (иначе агент отвечает про предыдущий документ), обновлять ли память
    треда о файлах и восстанавливать ли текст вложения.

    ⚠️ `detach_files` (крестик в интерфейсе) СЧИТАЕТСЯ новым файлом: он стирает память треда,
    и без этого выходило «открепил, а он всё равно в контексте» — живая жалоба.
    """
    data = session_data or {}
    return bool(attachments) or bool(data.get("file_ids")) or bool(data.get("detach_files"))


async def resolve_history_limit(compact_summary: str, config, runtime_settings) -> int:
    """Сколько реплик истории брать. При наличии саммери лимит СВОЙ.

    ⚠️ Иначе саммери и полная история едут вместе: за один и тот же кусок диалога платят
    дважды, а окно модели тратится на пересказ рядом с оригиналом.
    """
    history_limit = runtime_settings.get_agents(
        "chat_history_messages_limit", config.agents.chat_history_messages_limit
    )
    if not compact_summary:
        return history_limit
    return runtime_settings.get_agents("summary_keep_recent", config.agents.summary_keep_recent)


@dataclass(slots=True)
class EngineInputs:
    """Файловые входы агента и окружение прогона. Пусто — значит in-process путь."""

    tabular_files: list[dict] | None = None
    reference_image_url: str | None = None
    has_non_tabular_attachment: bool = False
    repo_graph_ids: list[str] = field(default_factory=list)
    engine_env: dict[str, Any] = field(default_factory=dict)


async def collect_engine_inputs(
    *,
    config,
    redis_client,
    thread_id: str,
    user_id,
    attachments,
    session_data: dict | None,
    has_new_file: bool,
    agent_run_id: str | None = None,
) -> EngineInputs:
    """Что из файлов диалога уедет сайдкару и с каким окружением.

    🔴 ТОЛЬКО ДЛЯ HTTP-ПУТИ. In-process движок живёт в этом же процессе и ходит в хранилище
    напрямую — собирать ему презайнед-ссылки незачем, а снимок политики он и не примет
    (такого аргумента у него нет). Пустой результат здесь означает именно это, а не сбой.

    ⚠️ ФАЙЛЫ ДВУМЯ СПИСКАМИ, и круги не совпадают: таблицы — инструменту `analyze_data`
    (отбор по ФОРМЕ, что имеет смысл в SQL), всё приложенное — в песочницу (рабочее место
    человека). Пока импорт шёл по табличному списку, приложенный `.docx` в каталоге не
    появлялся вовсе, и файловым инструментам нечего было открывать.

    ⚠️ Ссылками, а не байтами: сайдкар качает сам и только если инструмент реально позван.
    """
    if not uses_http_engine(config, user_id):
        return EngineInputs()

    from service.services.chat.infrastructure import agent_context
    from service.services.chat.infrastructure.chat_worker.engine_env import build_engine_env

    tabular_files, dialog_files = await agent_context.collect_thread_files(
        redis_client, thread_id, user_id, session_data, has_new_file=has_new_file
    )
    (
        reference_image_url,
        has_non_tabular,
        repo_graph_ids,
    ) = await agent_context.collect_message_extras(
        redis_client,
        thread_id,
        attachments,
        detach_files=bool((session_data or {}).get("detach_files")),
        # Запасной источник признака «рядом с таблицей документ»: файлы диалога знает
        # backend, и клиенту для этого верить не нужно.
        dialog_files=dialog_files,
    )
    return EngineInputs(
        tabular_files=tabular_files,
        reference_image_url=reference_image_url,
        has_non_tabular_attachment=has_non_tabular,
        repo_graph_ids=repo_graph_ids,
        # Политика, overlay и песочница — см. `chat_worker/engine_env.py`.
        engine_env=await build_engine_env(
            redis_client,
            thread_id,
            user_id,
            dialog_files,
            session_data,
            agent_run_id,
        ),
    )


async def read_summary_or_empty(thread_id: str, config) -> str:
    """Готовое саммери треда из Redis. Fail-open: без него ход идёт по полной истории.

    🔴 КЛИЕНТ ЗДЕСЬ АСИНХРОННЫЙ, а у воркера синхронный. `read_cached_summary` ждёт
    `redis.asyncio`; передать ему воркерский клиент значит получить `await` на не-корутине —
    саммери всегда пустое, и компактизация молча не работает. Это уже случалось.
    """
    from service.infrastructure.cache.redis_manager import RedisManager
    from service.services.chat.infrastructure.agent_context import read_cached_summary

    try:
        return await read_cached_summary(str(thread_id), RedisManager(config.redis).get_client())
    except Exception:
        logger.debug(
            "саммери треда не прочитано — идём по полной истории",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
        return ""


# Потолок восстановленного текста — тот же, что у загрузки: вложение едет в промпт КАЖДЫМ
# ходом треда, и «прочитать целиком» здесь означает платить за это каждый раз.
_RECOVERED_TEXT_LIMIT = 5000
# Ниже этой доли «словных» символов считаем, что перед нами не текст, а бинарь.
_MIN_TEXT_QUALITY = 0.35


def decode_as_text(content: bytes) -> str:
    """Содержимое файла как текст — если это ТЕКСТ, а не бинарь.

    🔴 ЗАЧЕМ ОТДЕЛЬНО ОТ ПАРСЕРА ДОКУМЕНТОВ. `OpenDataLoaderParser` умеет PDF и DOCX, а на
    `.py`, `.md`, `.json`, `.yaml` возвращает ПУСТО — при любом ключе хранилища, проверено
    замером. Из-за этого восстановление текста вложения работало только для документов, и
    человек с приложенным кодом получал «пришлите код функции», хотя файл лежал в хранилище.

    ⚠️ Качество судим уже существующим правилом (доля символов в «словах»): бинарь после
    `decode(errors="replace")` рассыпается на одиночные символы и не пройдёт порог. Честное
    пусто лучше мусора в промпте — за мусор ещё и платят токенами каждый ход.
    """
    try:
        text = (content or b"").decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not text.strip():
        return ""
    from service.services.chat.application.use_cases.upload_file_use_case import _text_quality

    if _text_quality(text) < _MIN_TEXT_QUALITY:
        return ""
    return text[:_RECOVERED_TEXT_LIMIT]
