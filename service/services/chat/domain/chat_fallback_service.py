"""Деградация чата, когда очередь задач недоступна.

РАНЬШЕ здесь прогонялся агент ПРЯМО В ВЕБ-ПРОЦЕССЕ: своя копия ChatAgent, свой путь
инструментов, свой ответ. Это делало backend вторым движком — а после выноса домена в
сайдкар такой копии просто нет.

И удалять её стоило не только ради архитектуры. Собственный комментарий прежней
реализации гласил: «здесь пока НЕ тарифицируется — при недоступности воркера запросы
обслуживаются бесплатно (утечка выручки)». То есть падение celery превращалось в
бесплатную раздачу LLM-ответов, и чем дольше длился сбой, тем дороже он обходился.

Теперь путь честный: пользователю говорят, что сервис временно недоступен. Это хуже для
одного запроса, но лучше для системы — сбой виден, а не оплачивается нами молча.
"""

import logging

from service.services.chat.domain.chat_contracts import ChatProcessingMetadata, ChatReplyResult

logger = logging.getLogger(__name__)

_UNAVAILABLE_REPLY = (
    "Сервис временно перегружен и не может обработать сообщение. "
    "Попробуйте, пожалуйста, ещё раз через минуту."
)

# ⚠️ ДРУГОЙ случай, и путать их нельзя. Выше — задачу не удалось ПОСТАВИТЬ, отвечать
# некому. Здесь — задача поставлена и ИСПОЛНЯЕТСЯ, просто ответ не пришёл за отведённое
# ожидание (длинный документ, долгий инструмент). Воркер доведёт ход до конца, сохранит
# его сам и спишет деньги; повторная отправка означала бы второй платный прогон.
_STILL_PROCESSING_REPLY = (
    "Ответ готовится дольше обычного — он появится в этом диалоге сам. "
    "Отправлять сообщение заново не нужно."
)


def build_still_processing_result(thread_id: str) -> ChatReplyResult:
    """Ответ для случая «задача исполняется, ждать дольше не стали».

    Живой прогон: ожидание результата истекло на 30-й секунде, а воркер спокойно
    доработал и сохранил настоящий ответ. Пользователю при этом уходило «сервис
    перегружен» — то есть отказ поверх успешно выполненной и оплаченной работы.
    """
    return ChatReplyResult(
        reply=_STILL_PROCESSING_REPLY,
        thread_id=str(thread_id),
        metadata=ChatProcessingMetadata(data={"degraded": True, "reason": "result_wait_timeout"}),
    )


class ChatFallbackService:
    """Заглушка деградации: честный отказ вместо бесплатного in-process прогона."""

    def __init__(self, agent=None, file_service=None):
        # Параметры оставлены ради совместимости composition-графа: он собирает сервис
        # с агентом и файловым сервисом. Ни то, ни другое здесь больше не нужно.
        self.agent = agent
        self.file_service = file_service

    async def execute(
        self,
        thread_id: str,
        text: str,
        user_id: str | int | None,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        file_context: str,
        route_override: str | None,
        attachments: list | None = None,
    ) -> ChatReplyResult:
        logger.error(
            "очередь задач недоступна: сообщение НЕ обработано (thread=%s). Прежний "
            "in-process путь обслуживал такие запросы бесплатно — он удалён намеренно.",
            thread_id,
        )
        return ChatReplyResult(
            reply=_UNAVAILABLE_REPLY,
            thread_id=str(thread_id),
            metadata=ChatProcessingMetadata(
                data={"degraded": True, "reason": "job_queue_unavailable"}
            ),
        )
