"""Backend mirror of agent settings, preserving AGENTS__ environment names."""

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Agents(BaseModel):
    agents_two_phase: list[str] = Field(default_factory=list)


class AgentsConfig(BaseSettings):
    settings: Agents = Agents()
    llm_provider: str = "auto"
    harness_refinement_enabled: bool = False
    local_api_key: str = Field(default_factory=str)
    local_base_url: str = "http://local-llm:8080/v1"
    local_timeout_sec: float = Field(default=330.0, ge=1, le=600)
    local_models_cache_ttl_sec: int = Field(default=180, ge=1)
    max_turns: int = Field(default_factory=int)
    # Предохранитель на выборку истории из БД. Реальный лимит теперь токенный (см.
    # единый протокол контекста ниже): сколько реплик влезет — решает бюджет окна,
    # поэтому тянем с запасом, а не режем жёстко на 8.
    chat_history_messages_limit: int = 40
    # DEPRECATED: символьная отсечка контекста. Работает только в legacy-режиме при
    # token_budget_enabled=False. Штатный путь считает всё в токенах от окна модели.
    mem0_api_key: str = Field(default_factory=str)
    mem0_app_id: str = "gpthub"
    # --- Память: выбор провайдера и MemOS (self-hosted/cloud) ---
    memory_provider: str = "auto"  # auto | mem0 | memos | noop
    memos_base_url: str = Field(default_factory=str)
    memos_api_key: str = Field(default_factory=str)
    memos_mem_cube_id: str = "gpthub-{user_id}"
    memos_timeout_sec: float = 15.0
    memory_context_timeout_sec: float = Field(default=2.0, ge=0.1, le=10.0)
    memos_async_mode: str = "sync"
    # Предпочтительный эмбеддер общего шлюза, не жёсткая привязка к провайдеру.
    # GPTHub MemOS использует логический профиль gpthub-memory-embedding; каждая
    # комбинация провайдер/модель/размерность получает отдельный индекс без wipe.
    memos_embedder_model: str = "openrouter:openai/text-embedding-3-small"
    memos_embedder_dim: int = 1536
    # Совместимость прежних настроек админки; допуск доступных резервов принадлежит шлюзу.
    memos_embedder_fallback: list = Field(default_factory=list)
    # --- Deep research: провайдер и LDR (local-deep-research) микросервис ---
    # auto = LDR если доступен, иначе нативный deep_research(); native = только наш;
    # ldr = только LDR (при недоступности — ошибка/фолбэк на native).
    deep_research_provider: str = "auto"  # auto | ldr | native
    # ⚠️ Реестр админки ссылается на это поле; без него ВСЯ страница настроек падала
    # с AttributeError. Держит tests/test_settings_registry_resolves.py.
    # Потолок тела запроса к сайдкару. ⚠️ Поле объявлено ЗДЕСЬ, хотя читает его
    # `contracts.py`: `AgentsConfig` имеет `extra="forbid"`, и переменная
    # `AGENTS__MAX_BODY_BYTES` без объявления роняет СТАРТ обоих сервисов. Ровно так
    # `docker/.env.example` и превращал скопировавшего его в обладателя мёртвого стека.
    max_body_bytes: int = 64 * 1024 * 1024
    search_engine_timeout_sec: float = 5.0
    # ⚠️ DEPRECATED, поведения нет, из реестра админки убраны. Оставлены потому, что
    # `.env.*` в .gitignore: на хосте с ещё объявленной переменной `extra="forbid"` не даст
    # сервису стартовать. Снимать — после чистки переменных на всех хостах.
    token_budget_enabled: bool = True
    max_context_chars: int = 150_000
    plan_step_execution_enabled: bool = False
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
    # Режим движка: "http" — воркер стримит на сайдкар. Другого нет, `select_agent_engine`
    # отвергает "inprocess" явной ошибкой.
    # ⚠️ Дефолт обязан быть РАБОЧИМ: он оставался "inprocess" с тех времён, когда был
    # таковым, а `.env.prod` ключа не содержит — прод поднимался в режиме, который
    # фабрика отвергает, и падал на первом сообщении.
    engine_mode: str = "http"
    # КАНАРЕЙКА: список user_id (CSV) — исторический механизм постепенного перевода
    # на сайдкар. Сейчас через сайдкар идут все, и список ни на что не влияет;
    # оставлен как предикат, по которому воркер решает, класть ли в тело
    # презайнед-ссылки на файлы (см. `uses_http_engine`).
    engine_canary_user_ids: str = ""
    # Адрес сайдкара agents для engine_mode="http" (квартет как у прочих сайдкаров).
    # Таймаут щедрый: прогон агента с планированием/суб-агентами живёт минутами, а
    # обрыв по таймауту посреди стрима = потерянный (но уже оплаченный) ответ.
    sidecar_url: str = "http://agents:8090"
    sidecar_timeout_sec: float = 600.0
    proxy_host: str = Field(default_factory=str)
    proxy_port: int | None = None
    proxy_user: str = Field(default_factory=str)
    proxy_pass: str = Field(default_factory=str)
    # Провайдеры, для которых применяется прокси (CSV). Зарубежные (openrouter/openai)
    # ходят через прокси; российские (routerai/gigachat/mws) — напрямую. Пусто → ни для кого.
    proxy_providers: str = "openrouter,openai"
    mws_api_key: str = Field(default_factory=str)
    mws_base_url: str = Field(default_factory=str)
    mws_timeout_sec: float = 20.0
    mws_models_cache_ttl_sec: int = 180
    openai_api_key: str = Field(default_factory=str)
    openai_base_url: str = Field(default_factory=str)
    openrouter_api_key: str = Field(default_factory=str)
    openrouter_base_url: str = Field(default_factory=str)
    openrouter_timeout_sec: float = 20.0
    openrouter_models_cache_ttl_sec: int = 180
    # --- RouterAI (OpenAI-совместимый, https://routerai.ru/api/v1) ---
    routerai_api_key: str = Field(default_factory=str)
    # Общее окружение принимается backend; применение Image API принадлежит сайдкару.
    image_only_api_enabled: bool = False
    routerai_base_url: str = Field(default_factory=str)
    routerai_timeout_sec: float = 45.0
    routerai_models_cache_ttl_sec: int = 180
    # --- Whisper.cpp (локальная STT через сайдкар) ---
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
    # Суммарный потолок табличных файлов, отдаваемых в сайдкар за один вызов.
    duckdb_max_bytes: int = 48 * 1024 * 1024
    # --- MCP (инструменты чужих серверов; в сеть ходит САЙДКАР, backend их не читает) ---
    # ⚠️ Объявлены здесь по двум причинам: `extra="forbid"` отвергает незаявленную
    # `AGENTS__MCP_*` и роняет старт, а панель показывает «переопределено» относительно
    # дефолта отсюда — значит дефолты обязаны совпадать с сайдкаром.
    # --- workspace (файловая песочница; в сеть ходит САЙДКАР agents) ---
    workspace_enabled: bool = True
    workspace_url: str = "http://workspace:8080"
    workspace_timeout_sec: float = 120.0
    workspace_api_key: str = Field(default_factory=str)
    # Сколько просить у сайдкара. ⚠️ Привязка в Redis живёт ДОЛЮ этого срока
    # (BINDING_TTL_RATIO): иначе тред указывал бы на уже подметённый контейнер.
    workspace_ttl_sec: float = 1800.0
    # 🔴 ОТДЕЛЬНЫЙ ТУМБЛЕР СОЗДАНИЯ, и по умолчанию ВЫКЛЮЧЕН. `workspace_enabled` означает
    # «способность разрешена», а этот — «создавать песочницу треду автоматически». Разделены
    # не для красоты: у сайдкара ОБЩИЙ потолок песочниц (32), и автосоздание на тред
    # исчерпало бы его на платформе с обычным трафиком за минуты — молча, отказом «работа с
    # файлами недоступна» без единой ошибки. Включать осознанно и вместе с потолком.
    # ⚠️ Ключ BACKEND-ONLY: сайдкару agents он не пробрасывается (у него такого поля нет,
    # а `extra="forbid"` уронил бы старт).
    workspace_autocreate: bool = False
    # --- video (агент смотрит ролик; в сеть ходит САЙДКАР video) ---
    # ⚠️ Объявлены здесь по той же причине, что MCP: `extra="forbid"` роняет СТАРТ backend
    # на незаявленной `AGENTS__VIDEO_*` — `.env` у сервисов один. Дефолты совпадают с
    # сайдкаром: расхождение показало бы «переопределено» там, где не переопределяли.
    # 🔴 ВЫКЛЮЧЕН по умолчанию: включённый, он тратил бы деньги у всех, кто обновил образ.
    video_enabled: bool = False
    video_url: str = "http://video:8080"
    video_timeout_sec: float = 480.0
    video_api_key: str = Field(default_factory=str)
    mcp_enabled: bool = True
    mcp_servers: list = Field(default_factory=list)
    mcp_timeout_sec: float = 20.0
    mcp_resilience_mode: str = "observe"  # mirror agents admin snapshot
    mcp_circuit_failure_threshold: int = 3
    mcp_circuit_cooldown_sec: float = 60.0
    # --- Разбор репозитория по ссылке ---
    # Белый список хостов: клонировать по произвольному URL — это SSRF. Только https и
    # только эти хосты; архив тянем по HTTPS, git-бинарь не нужен.
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
    doc_embedder_fallback: list = Field(
        default_factory=lambda: [
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
    gigachat_authorization_key: str = Field(default_factory=str)
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_base_url: str = Field(default_factory=str)
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_verify_ssl: bool = True
    gigachat_ca_bundle: str = Field(default_factory=str)
    gigachat_timeout_sec: float = 30.0
    gigachat_models_cache_ttl_sec: int = 180
    gigachat_token_skew_sec: int = 60
    # --- Реестр провайдеров: ретраи и фейловер (Фаза 1) ---
    # Фейловер включён по умолчанию (устойчивость): при сбое активного провайдера
    # запрос уходит на следующий из provider_fallback_order.
    provider_fallback_order: str = "openai,routerai,gigachat,mws"
    provider_failover_enabled: bool = True
    # Ручной вкл/выкл провайдера админом (чекбокс). Мапа {name: bool}; отсутствие ключа =
    # включён. Выключенный провайдер скрыт у пользователей и не пробуется фейловером.
    provider_enabled: dict = Field(default_factory=dict)
    llm_retry_attempts: int = 2
    llm_retry_budget_sec: float = Field(default=5.0, ge=0.1, le=30.0)
    llm_retry_base_delay_sec: float = 0.4
    llm_retry_max_delay_sec: float = 4.0
    auto_orchestrator_enabled: bool = True  # умный «Авто»; ЧИТАЕТ САЙДКАР, здесь — для админки
    auto_confirm_modes: str = (
        "deep_research,pptx_gen,pdf_gen,research_deck,research_pdf_presentation"
    )
    # ⚠️ ЧИТАЕТ САЙДКАР, объявлено и здесь: `.env` у сервисов ОДИН, а `extra="forbid"`
    # роняет СТАРТ backend на любом незнакомом `AGENTS__*` (живая restart-петля).
    mode_offer_ttl_sec: int = 30
    multi_intent_enabled: bool = False
    max_subtasks: int = 3
    reroute_on_failure_enabled: bool = True
    subtask_synthesis_max_tokens: int = 1200
    personas: dict = Field(default_factory=dict)
    workflow_catalog_enabled: bool = True
    workflow_catalog_collection: str = "gpthub_workflow_catalog"
    workflow_catalog_top_k: int = 5
    workflow_catalog_min_similarity: float = 0.78
    workflow_catalog_outbox_lease_sec: int = 120
    workflow_catalog_outbox_retry_max_sec: int = 3600
    tool_dedup_mode: str = "observe"  # mirror agents admin snapshot
    instructions_max_chars: int = 3000
    persona_max_tokens: int = 800  # зеркало сайдкара; 320 обрезало тон, формат и оговорки
    chat_max_tokens: int = 4096
    chat_max_continuations: int = 2
    chat_max_prompt_tokens_per_run: int = 40_000
    tool_disclosure_mode: str = "observe"  # off | observe | enforce
    tool_disclosure_min_candidate_count: int = 15
    tool_disclosure_timeout_sec: float = 8.0
    tool_disclosure_canary_user_ids: str = ""
    context_token_budget: int = 0
    context_safety_margin: float = 0.85  # зазор 15% на неточность оценки токенов
    context_output_reserve: int = 0  # 0 → берём chat_max_tokens (место под ответ)
    context_prompt_overhead: int = 1000  # системный промпт агента + схемы инструментов
    context_default_window: int = 32768  # окно неизвестной модели (консервативно)
    context_budget_history: float = 0.30
    context_budget_memory: float = 0.15
    context_budget_plan: float = 0.10
    context_budget_files: float = 0.35  # вложения — это задача, которую ставит юзер
    context_budget_knowledge: float = 0.15
    context_budget_facts: float = 0.05
    context_budget_summary: float = 0.05
    context_compression_enabled: bool = True  # сжимать крупные источники, а не резать
    compaction_threshold: float = 0.85  # доля usable, при которой авто-компактизация
    history_summary_enabled: bool = True  # компактизация контекста + саммери в MemOS
    summary_trigger_messages: int = 12
    summary_keep_recent: int = 6
    summary_max_tokens: int = 400
    run_timeout_sec: float = 570.0
    model_config = SettingsConfigDict(env_prefix="AGENTS__")

    @field_validator("proxy_port", mode="before")
    @classmethod
    def _normalize_proxy_port(cls, value):
        if value in (None, ""):
            return None
        return value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalize_llm_provider(cls, value):
        provider = str(value or "auto").strip().lower()
        if not (
            provider
            and len(provider) <= 64
            and provider.isascii()
            and provider[0].isalpha()
            and provider.replace("_", "").replace("-", "").isalnum()
        ):
            return "auto"
        return provider

    @field_validator("gigachat_scope", mode="before")
    @classmethod
    def _normalize_gigachat_scope(cls, value):
        scope = str(value or "GIGACHAT_API_PERS").strip().upper()
        if scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_CORP", "GIGACHAT_API_B2B"}:
            return "GIGACHAT_API_PERS"
        return scope

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

    @field_validator("chat_history_messages_limit", mode="before")
    @classmethod
    def _normalize_positive_int(cls, value):
        if value in (None, ""):
            return 0
        try:
            parsed = int(value)
        except (ValueError, TypeError):
            return 0
        return max(parsed, 0)
