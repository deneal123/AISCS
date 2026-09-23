"""Фиксация результата хода: деньги, метаданные для человека, запись в БД.

Отдельный узел, а не часть большой функции воркера: у него своя причина меняться — КАК мы
фиксируем итог (что списываем, что показываем, что сохраняем), тогда как соседние узлы
меняются от источников контекста и от того, чем исполняется прогон.

⚠️ ПОРЯДОК ЗДЕСЬ НЕСУЩИЙ, и каждый шаг оплачен своим инцидентом:
* списание идёт ДО записи хода — иначе на момент записи usage ещё не существует, и в
  сообщение физически нечего положить;
* usage роутера добавляется ОТДЕЛЬНЫМ событием: он посчитан в веб-процессе и без этого
  сгорал бы мимо биллинга;
* метаданные для человека собираются ПОСЛЕ обоих списаний — иначе стоимость в интерфейсе
  меньше фактической.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from service.services.chat.infrastructure.chat_worker.charging import (
    _charge_router_usage,
    _charge_usage,
)
from service.services.chat.infrastructure.chat_worker.message_meta import (
    build_public_usage_meta,
)
from service.services.chat.infrastructure.chat_worker.services import (
    ChatWorkerConversationService,
)
from service.services.chat.persistence.chat_worker_repository import ChatWorkerRepository

logger = logging.getLogger(__name__)


async def charge_and_describe(
    *,
    pg_connector,
    redis_client,
    config,
    execution_result: dict,
    session_data: dict | None,
    metadata: dict,
    thread_id: str,
    job_id: str,
    user_id: str | None,
    resolved_model: str | None,
    selected_model: str | None,
    reservation_id: str | None,
    reserved_estimate: int,
    started_at: float,
) -> tuple[int, dict]:
    """Списать за ход и собрать метаданные стоимости. → ``(снято_кредитов, метаданные)``.

    🔴 СПИСАНИЙ ДВА, И ВТОРОЕ ЛЕГКО ЗАБЫТЬ. Основное — за ответ; отдельное — за вызов
    роутера, посчитанный ещё в веб-процессе и приехавший в `session_data`. Без второго его
    токены сгорали бы мимо биллинга: платформа платит провайдеру, а в счёт это не попадает.

    ⚠️ Возвращаем СУММУ обоих: на этом числе висят и реституция при сбое, и стоимость хода,
    которую видит человек. Занизить его — значит вернуть больше, чем сняли.
    """
    price_breakdown: dict = {}
    charged = await _charge_usage(
        pg_connector=pg_connector,
        redis_client=redis_client,
        user_id=user_id,
        execution_result=execution_result,
        thread_id=thread_id,
        job_id=job_id,
        resolved_model=resolved_model,
        config=config,
        selected_model=selected_model,
        reservation_id=reservation_id,
        reserved_estimate=reserved_estimate,
        breakdown_out=price_breakdown,
    )
    # Неблокирующе: сбой этого списания не должен ронять уже отданный ответ.
    charged += await _charge_router_usage(
        pg_connector=pg_connector,
        redis_client=redis_client,
        user_id=user_id,
        session_data=session_data,
        thread_id=thread_id,
        job_id=job_id,
        config=config,
    )

    usage_meta = build_public_usage_meta(
        execution_result,
        charged_credits=charged,
        model=resolved_model or selected_model,
        duration_ms=int((time.monotonic() - started_at) * 1000),
        breakdown=price_breakdown,
    )
    return charged, ({**metadata, "usage": usage_meta} if usage_meta else metadata)


def public_metadata(metadata: dict, usage_meta: dict | None) -> dict[str, Any]:
    """Метаданные ответа с блоком стоимости, если он собрался.

    ⚠️ Пустой блок НЕ кладём: «usage: {}» в интерфейсе читается как «ход бесплатный», а это
    разные вещи — не собрался и не стоил.
    """
    return {**metadata, "usage": usage_meta} if usage_meta else dict(metadata)


CANCELLED_NOTE = "_(остановлено пользователем)_"
INTERRUPTED_NOTE = "_(генерация прервана)_"


def interrupted_reply_text(streamed_parts: list[str] | None, *, cancelled: bool) -> str:
    """Что записать в историю за оборванный ход. Пустая строка — не записывать ничего.

    🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Пользователь спросил, через 8 с нажал «стоп» — и в треде не
    осталось НИЧЕГО: ни ответа, ни собственного вопроса. Прежнее правило («сохранять, если
    успели уйти токены») молчаливо теряло весь ход, когда отмена случалась ДО первого чанка,
    а именно так и бывает на дорогих путях: файлы, deep research, поиск в сети — там до
    первого токена уходят десятки секунд, и это ровно то время, когда жмут «стоп».

    ⚠️ ОТМЕНА И СБОЙ — РАЗНОЕ. Отмена намеренна: человек ждёт, что его вопрос останется на
    экране и после перезагрузки. Сбой же системный, и пустой ход без ответа выглядел бы
    мусором — там прежнее правило сохраняется дословно.
    """
    partial = "".join(streamed_parts or []).strip()
    if partial:
        return f"{partial}\n\n{CANCELLED_NOTE if cancelled else INTERRUPTED_NOTE}"
    return CANCELLED_NOTE if cancelled else ""


async def _persist_chat_turn(
    *,
    db_session,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    user_id: str | None,
    user_metadata: dict | None = None,
    assistant_metadata: dict | None = None,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
) -> bool:
    return await ChatWorkerConversationService(ChatWorkerRepository()).persist_turn(
        db_session=db_session,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        user_id=user_id,
        user_metadata=user_metadata,
        assistant_metadata=assistant_metadata,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )


async def _persist_partial_turn_committed(
    pg_connector, thread_id: str, user_text: str, partial_text: str, user_id, user_metadata=None
) -> None:
    """Сохранить ЧАСТИЧНЫЙ ответ (стрим оборвался ошибкой после уже отданных чанков)
    в ОТДЕЛЬНОЙ транзакции — worker-сессия к этому моменту rollback()-нута. Иначе
    пользователь видел текст, затем ошибку, а в истории было пусто. Best-effort:
    сбой лишь логируется и не маскирует исходную ошибку.

    ⚠️ ``user_metadata`` — ВЛОЖЕНИЯ реплики. Без них аварийный путь писал сообщение
    пользователя с пустой метой, и приложенный файл исчезал при перезагрузке."""
    if not str(partial_text or "").strip():
        return
    try:
        async with pg_connector.get_session_context() as s:
            await _persist_chat_turn(
                db_session=s,
                thread_id=thread_id,
                user_text=user_text,
                assistant_text=partial_text,
                user_id=user_id,
                user_metadata=user_metadata,
            )
            await s.commit()
    except Exception:
        logger.debug(
            "failed to persist partial turn for interrupted job",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
