"""Контракты слоя chat: то, чем обмениваются его сервисы между собой.

Жили в общем пакете с сайдкаром, хотя из шести структур двусторонней была ровно одна
(`ChatRouteDecision`, 10 строк), а `build_provider_unavailable_reply` нужен только
сайдкару. Остальное — внутренние типы оркестрации chat: их сайдкар не видел никогда.

Теперь у каждой стороны своё. Совпадение формы `ChatRouteDecision` держится тем, что
сайдкар отдаёт `/route` СЛОВАРЁМ, а его поля покрыты контрактом (`route_response_fields`
в `/health` + сверка на стороне backend) — то есть проводом, а не общим классом.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChatRequestContext:
    thread_id: str
    text: str
    user_id: str | int | None
    selected_model: str | None = None
    input_type: str | None = None
    web_search: bool = False
    deep_research: bool = False
    file_context: str = ""
    route_override: str | None = None
    attachments: list | None = None
    # 🔴 ЭТИ ДВА ПОЛЯ ОБЪЯВЛЕНЫ В СХЕМЕ HTTP-РУЧКИ И ДО СИХ ПОР НИКУДА НЕ ЕХАЛИ. Замер
    # сквозным прогоном путём человека: `.py` загружен, `file_ids` передан в
    # `/api/chats/{id}/message` — агент ответил «пришлите код функции». Признак «в этом
    # сообщении новый файл» считался ложным, поэтому не работали ни импорт в песочницу, ни
    # восстановление текста, ни память треда о файлах. WS-путь их возит своим каналом
    # (`session_data`), а HTTP молча терял — то есть ручка обещала то, чего не делала.
    file_ids: list[str] | None = None
    # Согласие на дорогой просмотр видео. Живёт ОДНО сообщение (см. `engine_env`).
    watch_video: bool = False
    confirm_expensive_run: bool = False
    confirmed_offer_id: str | None = None
    confirmed_resolved_category: str | None = None


@dataclass(slots=True)
class ChatProcessingMetadata:
    data: dict[str, Any] = field(default_factory=dict)

    def merged(self, extra: dict[str, Any]) -> "ChatProcessingMetadata":
        return ChatProcessingMetadata(data={**self.data, **extra})

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


@dataclass(slots=True)
class ChatRouteDecision:
    selected_model: str | None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    web_search: bool = False
    deep_research: bool = False
    route_override: str | None = None
    # usage LLM-роутера (посчитан при resolve_route в веб-процессе) — везём в воркер
    # для отдельной тарификации (аудит A2). Пусто, если роутер-LLM не звался.
    routing_usage: dict[str, Any] = field(default_factory=dict)
    # Категория агента, которую авто-роутер сайдкара УЖЕ выбрал. Проносим в воркер,
    # чтобы `/run` не роутил тот же текст вторым LLM-вызовом. Пусто при ручном выборе
    # модели — там авто-роутер не звался вовсе.
    resolved_category: str | None = None


@dataclass(slots=True)
class ChatReplyResult:
    reply: str
    thread_id: str | None
    file_url: str | None = None
    metadata: ChatProcessingMetadata = field(default_factory=ChatProcessingMetadata)

    def __post_init__(self) -> None:
        if isinstance(self.metadata, dict):
            self.metadata = ChatProcessingMetadata(data=self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "thread_id": self.thread_id,
            "file_url": self.file_url,
            "metadata": self.metadata.data,
        }


@dataclass(slots=True)
class JobExecutionResult:
    job_id: Any
    status: Any
    result_file_url: str | None = None
    wait_time_sec: int = 0
    celery_task_id: str | None = None


def build_provider_unavailable_reply(error_message: str | None = None) -> str:
    base = (
        "Сейчас не удалось получить ответ от модели. "
        "Проверьте API-ключ/доступ к провайдеру и повторите запрос."
    )
    if error_message:
        return f"{base} Детали: {error_message}"
    return base
