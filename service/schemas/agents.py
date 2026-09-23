"""Схемы агентного слоя (gpthub_core).

DTO домена агентов — контекст запроса, вложения, роутинг. Нужны И backend'у, И
сайдкару agents (тело ``/run`` и внутренние структуры пайплайна). Самодостаточны:
только stdlib + pydantic. ``UserContext`` — ядро: его собирает backend и получает
движок; ``history_messages``/``system_context`` — те самые поля, что переехали
ВВЕРХ в Фазе 0b (stateless).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModalityAttachment(BaseModel):
    """Одна модальность, уже сведённая к тексту на этапе загрузки.

    content — это VLM-описание изображения, транскрипт аудио или извлечённый
    текст документа. Используется мультимодальным fan-out конвейером.
    """

    kind: str = Field("document", description="image | audio | document | other")
    name: str = Field("", description="Имя исходного файла")
    file_id: str | None = Field(None, description="Opaque owner-checked Library identifier")
    mime_type: str | None = Field(None, description="Normalized media type")
    digest: str | None = Field(None, description="SHA-256 of the owned source")
    content: str = Field("", description="Извлечённый текст модальности")
    # Презайнед-ссылка на ОРИГИНАЛ в нашем хранилище. Нужна, когда угла зрения, выбранного
    # на аплоаде, недостаточно: личность может потребовать посмотреть на пиксели иначе, а
    # `content` к тому моменту уже текст. Возим ССЫЛКУ, а не байты: тело `/run` и так несёт
    # историю и контекст, и раздувать его мегабайтами ради ветки, которая срабатывает у
    # меньшинства, нельзя. Тот же приём, что у `tabular_files` (скачиваем ЛЕНИВО и только
    # когда действительно понадобилось).
    source_url: str | None = Field(
        None,
        description="Презайнед-ссылка на оригинал",
        exclude=True,
    )

    model_config = ConfigDict(extra="ignore")


class UserContext(BaseModel):
    user_id: str = Field(..., description="Идентификатор пользователя")
    request_time: datetime = Field(..., description="Время запроса")
    thread_id: str | None = Field(None, description="Идентификатор треда/разговора")
    previous_questions: list[dict] | None = Field(
        None, description="Список предыдущих запросов пользователя"
    )
    session: Any | None = Field(
        None, description="Объект сессии (RedisSession, PseudoSession и т.д.)"
    )
    session_id: str | None = Field(
        None, description="Идентификатор разговорной сессии для хранения истории"
    )
    session_store: dict[str, Any] | None = Field(None, description="Метаданные о backend'е сессии")
    history_messages: list[dict] | None = Field(
        None, description="История диалога как массив реплик [{role, content}] для chat-моделей"
    )
    system_context: str | None = Field(
        None, description="Системный контекст (память, план, вложения) для system-сообщения"
    )
    current_attachments: list[ModalityAttachment] | None = Field(
        None,
        description=(
            "Структурированные вложения только текущего run; subagents читают их явно, "
            "не разбирая текстовые markers системного контекста"
        ),
    )
    declined_mode: str | None = Field(
        None,
        description=(
            "Дорогой режим, который НЕ запущен и предложен кнопкой. Без этого поля ответ "
            "обещал выполнить работу, которой не делает"
        ),
    )
    has_non_tabular_attachment: bool = Field(
        False,
        description=(
            "В сообщении есть нетабличный файл рядом с табличным → не выбрасывать "
            "file_context при наличии таблиц"
        ),
    )
    # Ссылка на файловую песочницу этого прогона: {workspace_id, token, user_id, root}.
    # 🔴 ТОКЕН ВЛАДЕНИЯ, а не только идентификатор: сайдкар обязан отличить владельца от
    # того, кто подставил чужой `workspace_id`. Приходит от backend'а — модель к нему не
    # прикасается, иначе она называла бы чужие песочницы.
    # Пусто — шесть инструментов `ws_*` отсеиваются гейтом, и чат идёт как прежде.
    workspace_ref: dict | None = Field(
        None,
        description="Ссылка на песочницу прогона",
        exclude=True,
    )
    # Оркестратор решил, что задача про файлы. Только по этому признаку выдаются шесть
    # инструментов `ws_*`: их схемы стоят токенов в каждом запросе, а вызов гонит весь
    # контекст вторым кругом. Тот же приём, что у `web_tool_enabled`.
    workspace_tools_enabled: bool = Field(False, description="Оркестратор запросил файлы")
    # 🔴 СОГЛАСИЕ ЧЕЛОВЕКА, А НЕ РЕШЕНИЕ ОРКЕСТРАТОРА. Просмотр ролика — дорогая
    # способность: сотня кадров переезжает в контекст КАЖДОГО следующего сообщения треда.
    # Поэтому признак ставится только по явному подтверждению, тем же способом, что
    # `web_search`/`deep_research` у пользовательских тумблеров. Пусто — инструмент
    # отсеивается гейтом с причиной `needs_confirmation`, и чат идёт как прежде.
    video_tool_enabled: bool = Field(False, description="Человек подтвердил просмотр видео")
    repo_graph_ids: list[str] | None = Field(
        None,
        description=("graph_id репозиториев треда — search_knowledge_graph ищет код репо в них"),
    )
    web_tool_enabled: bool = Field(
        False,
        description=(
            "Авто-оркестратор решил, что ответ упирается в устаревающие факты → выдать "
            "general инструмент веб-поиска. Гейт СТРУКТУРНЫЙ, как у analyze_data: без "
            "него схема инструмента ехала бы в каждом запросе, включая «привет»"
        ),
    )
    reference_image_url: str | None = Field(
        None,
        description=(
            "Презайнед-ссылка на последнюю картинку треда для image-to-image "
            "(«перегенерируй с другим цветом волос»); собрана бэкендом"
        ),
        exclude=True,
    )
    tabular_files: list[dict] | None = Field(
        None,
        description=(
            "Презайнед-ссылки на табличные файлы для инструмента analyze_data "
            "[{name, url}] — собраны бэкендом; сайдкар качает их лениво, без PG/MinIO"
        ),
        exclude=True,
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RoutingDecision(BaseModel):
    category: str = Field(..., description="Выбранная категория запроса")
