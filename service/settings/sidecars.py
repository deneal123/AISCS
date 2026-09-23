"""Соседние сервисы: адреса, таймауты, тумблеры и то, что они индексируют.

Квартет `<имя>_enabled/_url/_timeout_sec/_max_bytes` держим вместе, а не рядом с
потребителем: так видно, чего у нового сайдкара не хватает.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SidecarSettings(BaseModel):
    """Поля соседних сервисов. Собирается в `AgentsConfig`, отдельно не читается."""

    mem0_api_key: str = Field(default_factory=str)
    mem0_app_id: str = "gpthub"
    # --- Память: выбор провайдера и MemOS (self-hosted/cloud) ---
    # ⚠️ Сайдкар это поле не читает (память собирает backend), но удалять нельзя:
    # переменная задана в env-файлах, а `extra="forbid"` делает незаявленную отказом старта.
    memory_provider: str = "auto"  # auto | mem0 | memos | noop — ЧИТАЕТ BACKEND
    memos_base_url: str = Field(default_factory=str)
    memos_api_key: str = Field(default_factory=str)
    memos_mem_cube_id: str = "gpthub-{user_id}"
    memos_timeout_sec: float = 15.0
    memos_async_mode: str = "sync"
    # Эмбеддер MemOS (админ-настройка). memos читает эти значения при старте (env
    # MOS_EMBEDDER_MODEL/EMBEDDING_DIMENSION как фолбэк). Смена → полный wipe памяти
    # MemOS (коллекция Qdrant привязана к размерности) + рестарт memos.
    memos_embedder_model: str = "openrouter:openai/text-embedding-3-small"
    memos_embedder_dim: int = 1536
    # Фолбэк-эмбеддеры MemOS: если провайдер активного memos-эмбеддера заблокирован, каскад
    # переключает memos на первый рабочий из списка + СТИРАЕТ память MemOS (dim меняется).
    # ⚠️ memos применяет новый эмбеддер только после РЕСТАРТА контейнера (нет hot-reload):
    # до рестарта память пуста/fail-open. [] = авто-переключение выключено.
    memos_embedder_fallback: list = Field(default_factory=list)
    # --- Deep research: провайдер и LDR (local-deep-research) микросервис ---
    # auto = LDR если доступен, иначе нативный deep_research(); native = только наш;
    # ldr = только LDR (при недоступности — ошибка/фолбэк на native).
    deep_research_provider: str = "auto"  # auto | ldr | native
    ldr_base_url: str = Field(default_factory=str)  # http://gpthub-ldr-ldr-1:5000
    ldr_username: str = Field(default_factory=str)  # сервис-аккаунт (секрет)
    ldr_password: str = Field(default_factory=str)  # сервис-аккаунт (секрет)
    ldr_model: str = (
        "openrouter:openai/gpt-4o-mini"  # <provider>:<model> для шлюза; в прайс-реестре
    )
    ldr_search_engines: str = "searxng"  # CSV → список движков LDR
    ldr_strategy: str = "langgraph-agent"  # стратегия LDR (буст качества)
    ldr_iterations: int = 3
    ldr_timeout_sec: float = 240.0  # дедлайн опроса, < Celery soft-limit 300с
    ldr_poll_interval_sec: float = 3.0
    # --- OpenAI-совместимый шлюз (для LDR и др. внешних OpenAI-клиентов) ---
    # Проксирует к нашему мульти-провайдерному слою (failover, GigaChat OAuth).
    # Маршрут провайдера по префиксу модели "<provider>:<model>".
    llm_gateway_enabled: bool = False
    llm_gateway_api_key: str = Field(default_factory=str)  # bearer-ключ (секрет)
    # ⚠️ `engine_mode`/`engine_canary_user_ids` удалены: режим выбирает backend, сайдкар
    # всегда исполнитель. Живой флаг остался один — backend'овский `agents.engine_mode`.
    #
    # Таймаут щедрый: прогон с планированием живёт минутами, а обрыв посреди стрима —
    # это потерянный, но уже оплаченный ответ.
    sidecar_url: str = "http://agents:8090"
    sidecar_timeout_sec: float = 600.0
    whisper_enabled: bool = True
    whisper_url: str = "http://whisper:8080"
    whisper_default_model: str = "base"
    whisper_language: str = "ru"
    whisper_timeout_sec: float = 600.0
    # Цена локальной транскрипции: базовая ставка ₽/мин × множитель тира модели.
    whisper_price_rub_per_min: float = 0.05
    whisper_model_multipliers: dict[str, float] = Field(
        default_factory=lambda: {
            "base": 1.0,
            "small": 2.0,
            "medium": 4.0,
            "large-v3-turbo-q5_0": 5.0,
            "large-v3-turbo": 6.0,
            "large-v3": 8.0,
        }
    )
    # --- OpenDataLoader (парсинг документов в markdown через сайдкар) ---
    # Сайдкар отдаёт СТРУКТУРНЫЙ markdown (заголовки/таблицы/списки) вместо плоского
    # текста PyPDF2. Fail-open: недоступен → бэкенд молча падает на старый путь.
    opendataloader_enabled: bool = True
    opendataloader_url: str = "http://opendataloader:8080"
    opendataloader_timeout_sec: float = 180.0
    opendataloader_max_bytes: int = 20 * 1024 * 1024
    # --- graphify (граф знаний: код и документы) ---
    # Два режима разной цены. Код (zip) — tree-sitter AST, БЕЗ единого вызова LLM.
    # Документы — семантический проход LLM: он идёт через наш шлюз, а шлюз кредиты НЕ
    # списывает → тарифицируем явно (graph_index_price_rub_per_doc).
    graphify_enabled: bool = True
    graphify_url: str = "http://graphify:8080"
    graphify_timeout_sec: float = 900.0
    graphify_max_bytes: int = 50 * 1024 * 1024
    # Модель семантического прохода (её же compose отдаёт сайдкару как GFY_MODEL).
    graphify_model: str = "openrouter:openai/gpt-4o-mini"
    # --- duckdb (SQL/аналитика по табличным файлам) ---
    # Инструмент analyze_data гоняет SQL по загруженным csv/xlsx/parquet/json через
    # сайдкар DuckDB. Fail-open: недоступен → инструмент отвечает моделью словами.
    duckdb_enabled: bool = True
    duckdb_url: str = "http://duckdb:8080"
    duckdb_timeout_sec: float = 60.0
    # --- workspace (файловая песочница агента) ---
    # Квартет соседа. ⚠️ Ключ здесь — тот же `WORKSPACE_API_KEY`, что у самого сайдкара:
    # он закрывает сервис, которому отдан docker.sock, и без него вызовы уйдут в отказ.
    workspace_enabled: bool = True
    workspace_url: str = "http://workspace:8080"
    workspace_timeout_sec: float = 120.0
    workspace_api_key: str = Field(default_factory=str)
    # --- video (агент смотрит ролик) ---
    # 🔴 ВЫКЛЮЧЕН ПО УМОЛЧАНИЮ, в отличие от соседей. Просмотр ролика — самая дорогая
    # способность после ресёрча: сотня кадров переезжает в контекст КАЖДОГО следующего
    # сообщения треда. Способность, включённая дефолтом, начала бы тратить деньги у всех,
    # кто просто обновил образ; включает её админ осознанно.
    video_enabled: bool = False
    video_url: str = "http://video:8080"
    # Клиентский таймаут БОЛЬШЕ серверного дедлайна сайдкара (VIDEO_WATCH_TIMEOUT_SEC=420):
    # иначе клиент уходит раньше, чем сервер успевает ответить отказом, и причина теряется.
    video_timeout_sec: float = 480.0
    video_api_key: str = Field(default_factory=str)
    # --- MCP (инструменты чужих серверов) ---
    # 🔴 Серверы объявляет АДМИН и только он: адрес из тела запроса — это прямой SSRF во
    # внутреннюю сеть. Арендатору в `/run` приезжает лишь список разрешённых
    # ИДЕНТИФИКАТОРОВ, а сопоставление «идентификатор → адрес и секрет» живёт здесь.
    # Формат элемента: {id, url, transport, auth_header, auth_token, allowed_tools, enabled}.
    mcp_enabled: bool = True
    mcp_servers: list = Field(default_factory=list)
    mcp_timeout_sec: float = 20.0
    # Discovery resilience is staged: observe collects circuit signals but still tries;
    # enforce skips an already-open server. Tool calls themselves are never retried.
    mcp_resilience_mode: str = "observe"  # off | observe | enforce
    mcp_circuit_failure_threshold: int = 3
    mcp_circuit_cooldown_sec: float = 60.0
    # --- веб-поиск ---
    # Сколько даём ОДНОМУ поисковому движку. Общий бюджет поиска выводится отсюда
    # (search_budget_sec = таймаут × число движков + запас), а не задаётся отдельно:
    # два независимых числа уже разъехались однажды — движку давали 15 с при общем
    # бюджете 16 с, и четыре движка из пяти не запускались НИКОГДА.
    duckdb_max_bytes: int = 48 * 1024 * 1024
    # --- Разбор репозитория по ссылке ---
    # Белый список хостов: клонировать по произвольному URL — это SSRF. Только https и
    # только эти хосты; архив тянем по HTTPS, git-бинарь не нужен.
    search_engine_timeout_sec: float = 5.0
    # Суммарный потолок табличных файлов, отдаваемых в сайдкар за один вызов.
    repo_allowed_hosts: str = "github.com,gitlab.com,bitbucket.org"
    repo_max_bytes: int = 50 * 1024 * 1024
    repo_fetch_timeout_sec: float = 120.0
    # Индексация загруженных документов в личный граф пользователя (фоном).
    graph_index_enabled: bool = True
    graph_index_price_rub_per_doc: float = 0.5
    # --- Векторный поиск по документам (вторая половина гибридного поиска) ---
    # Граф отвечает на РЕЛЯЦИОННЫЕ вопросы (что с чем связано), эмбеддинги — на
    # «что там написано про X». Одно другое не заменяет, поэтому работают вместе.
    vector_search_enabled: bool = True
    qdrant_url: str = "http://qdrant:6333"
    doc_vector_collection: str = "gpthub_docs"
    # GigaChat, а не OpenAI: продукт русскоязычный, провайдер российский и не делит
    # исчерпаемый бюджет ключа OpenRouter с чат-моделями. Коллекция у нас своя
    # (gpthub_docs), MemOS со своим эмбеддером не пересекается.
    doc_embedder_model: str = "gigachat:Embeddings"
    # ⚠️ Коллекция Qdrant жёстко привязана к размерности: сменить эмбеддера = пересоздать
    # коллекцию, иначе поиск молча деградирует или падает.
    doc_embedder_dim: int = 1024
    # Фолбэк-эмбеддеры (отказоустойчивость): если основной эмбеддер-провайдер мёртв/заблокирован
    # или падает, doc-vector автоматически переходит на первый рабочий из списка. При СМЕНЕ
    # размерности коллекция gpthub_docs пересоздаётся (старые векторы стираются — стабильность
    # важнее сохранности индекса). Список: [{"model": "<provider>:<model>", "dim": N}, ...].
    #
    # ⚠️ ДВА фолбэка, и RouterAI первым. Цепочка из одного — не отказоустойчивость: в
    # живом инциденте gigachat отдал 429, единственный фолбэк был заблокирован
    # health-проверкой, и индексация документов встала целиком.
    doc_embedder_fallback: list = Field(
        default_factory=lambda: [
            {"model": "routerai:openai/text-embedding-3-small", "dim": 1536},
            {"model": "openrouter:openai/text-embedding-3-small", "dim": 1536},
        ]
    )
    doc_chunk_tokens: int = 700
    doc_chunk_overlap_tokens: int = 100
    # Потолок ВХОДА эмбеддера в токенах. У GigaChat-эмбеддера это 514 — чанк больше
    # даёт 413 «Tokens limit exceeded» и рушит индексацию документа. chars_for_tokens
    # намеренно занижает символы, поэтому чанк на 700 «наших» токенов реально тянул на
    # 534 токена GigaChat. Режем размер чанка до этого потолка (с запасом). Если у вас
    # только OpenAI-эмбеддер (лимит 8191) — можно поднять.
    doc_embedder_max_tokens: int = 480
    doc_vector_top_k: int = 5
    # Максимум вложений на сообщение. Каждое — отдельный LLM-вызов в fan-out.
    max_attachments_per_message: int = 8
    # Потолок текста вложения. Раньше был захардкожен в 15 000 символов — документ
    # обрезался ДО того, как его увидит бюджет контекста, и map-reduce сжимать было
    # уже нечего (модель видела ~28% статьи). Теперь текст доезжает целиком, а под
    # окно модели его ужимает context_compressor. Потолок нужен лишь как страховка
    # от патологии (выгрузка на мегабайты); он заведомо выше любого окна.
    attachment_text_max_chars: int = 400_000
    # Лимит загрузки файла (было захардкожено 20 МБ в use case).
    upload_max_bytes: int = 20 * 1024 * 1024
    # --- GigaChat (Сбер): OAuth2 + российские TLS-сертификаты ---

    @field_validator("memory_provider", mode="before")
    @classmethod
    def _normalize_memory_provider(cls, value):
        provider = str(value or "auto").strip().lower()
        if provider not in {"auto", "mem0", "memos", "noop"}:
            return "auto"
        return provider

    @field_validator("deep_research_provider", mode="before")
    @classmethod
    def _normalize_deep_research_provider(cls, value):
        provider = str(value or "auto").strip().lower()
        if provider not in {"auto", "ldr", "native"}:
            return "auto"
        return provider
