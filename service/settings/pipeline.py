"""Конвейер: маршрутизация, личности, протокол контекста, дедлайны прогона."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

_DEFAULT_AUTO_CONFIRM_MODES = (
    "deep_research,pdf_gen,research_pdf_presentation,research_pdf_document"
)


def _default_personas() -> dict[str, Any]:
    """Поставляемый реестр личностей — из домена, а не из настроек.

    Импорт ЛОКАЛЬНЫЙ и намеренно: `service.domain.persona.seed` держит данные рядом со своей
    схемой, а тянуть домен на уровне модуля настроек значило бы замкнуть круг
    (настройки → домен → настройки).
    """
    from service.domain.persona.seed import DEFAULT_PERSONAS

    return dict(DEFAULT_PERSONAS)


class Agents(BaseModel):
    agents_two_phase: list[str] = Field(default_factory=list)


class PipelineSettings(BaseModel):
    """Поля конвейера. Собирается в `AgentsConfig`, отдельно не читается."""

    settings: Agents = Agents()
    max_turns: int = Field(default_factory=int)
    # Предохранитель на выборку истории из БД. Реальный лимит теперь токенный (см.
    # единый протокол контекста ниже): сколько реплик влезет — решает бюджет окна,
    # поэтому тянем с запасом, а не режем жёстко на 8.
    chat_history_messages_limit: int = 40
    # DEPRECATED: символьная отсечка контекста. Работает только в legacy-режиме при
    # token_budget_enabled=False. Штатный путь считает всё в токенах от окна модели.
    auto_orchestrator_enabled: bool = True  # умный «Авто»; выключение = прежний роутер целиком
    auto_confirm_modes: str = _DEFAULT_AUTO_CONFIRM_MODES  # дорогие — по кнопке
    # Сколько живёт предложение дорогого режима. Отсчёт идёт от СЕРВЕРНОГО `offered_at`,
    # клиент по нему только рисует остаток. Молчание = отказ: автозапуск по таймауту
    # списал бы тысячи кредитов у человека, который отошёл от экрана.
    mode_offer_ttl_sec: int = 30
    # --- Роутинг: мульти-интент и ре-роут (Фаза 2) ---
    multi_intent_enabled: bool = False
    max_subtasks: int = 3
    reroute_on_failure_enabled: bool = True
    subtask_synthesis_max_tokens: int = 1200
    # --- Личности (persona): специализация, текущая вглубь до субагентов ---
    # Реестр редактируется в админке как JSON. Схема, словарь слотов и ПОСТАВЛЯЕМЫЕ ПО
    # УМОЛЧАНИЮ личности — в `service/domain/persona/` (данные держим там же, где их
    # схема, а не в настройках: иначе настройки растут данными и расходятся со схемой).
    personas: dict = Field(default_factory=_default_personas)
    # Автономный каталог workflow: PostgreSQL backend — источник правды; sidecar держит
    # лишь изолированную Qdrant-проекцию без текстов запросов и без user_id.
    workflow_catalog_enabled: bool = True
    workflow_catalog_collection: str = "gpthub_workflow_catalog"
    workflow_catalog_top_k: int = 5
    workflow_catalog_min_similarity: float = 0.78
    workflow_catalog_outbox_lease_sec: int = 120
    workflow_catalog_outbox_retry_max_sec: int = 3600
    # Потолок БАЗОВЫХ инструкций агента (был литералом 3000 в `_compose_system_instructions`).
    instructions_max_chars: int = 3000
    # Отдельный бюджет секции «Специализация»: у каждой части системного промпта свой,
    # иначе личность и инструкции вытесняли бы друг друга слепой общей обрезкой.
    # ⚠️ 800, А НЕ 320: прежнее значение стояло в восьми токенах от худшей связки в
    # поставке (312 из 320), а обрезается у секции ХВОСТ — тон, формат и оговорки, то
    # есть ровно то, что отличает личность. Запас держит `test_persona_budget_has_headroom`.
    persona_max_tokens: int = 800
    # --- Лимит длины ответа чата (стрим general-агента) ---
    # Потолок токенов на один вызов chat/completions. Был захардкожен 900 →
    # длинные ответы обрезались на полуслове. При достижении лимита включается
    # авто-продолжение (до chat_max_continuations раз) — стыкуем ответ бесшовно.
    chat_max_tokens: int = 4096
    chat_max_continuations: int = 2
    # Суммарный потолок prompt-токенов на один agent-run. Это страховка от
    # повторной отправки большого контекста в tool-loop; 0 отключает лимит.
    chat_max_prompt_tokens_per_run: int = 40_000
    # Прогрессивная выдача инструментов. По умолчанию выключена: rollout начинается с
    # observe, который считает эффект, но сохраняет исходный ToolSet для основной модели.
    tool_disclosure_mode: str = "observe"  # off | observe | enforce
    tool_disclosure_min_candidate_count: int = 15
    tool_disclosure_timeout_sec: float = 8.0
    # CSV user_id. Пусто = все пользователи выбранного режима; нужен для canary enforce.
    tool_disclosure_canary_user_ids: str = ""
    # Run-scoped result cache for repeated canonical tool calls. Observe records
    # the signal; enforce reuses a completed outcome without charging it again.
    tool_dedup_mode: str = "observe"  # off | observe | enforce
    # --- Единый протокол контекста ---
    # Бюджет контекста ВЫВОДИТСЯ из реального окна выбранной модели, а не задаётся
    # константой: usable = window*safety_margin - output_reserve - overhead.
    # Раньше был фикс 6000 токенов, никак не связанный с моделью, — на модели со
    # 128k окном мы использовали 5% её объёма, а на мелкой могли переполнить окно.
    # 0 = считать от окна модели (штатно). >0 = жёсткий потолок сверху, независимо от
    # окна (для контроля стоимости: не даём раздувать промпт даже на 1M-моделях).
    context_token_budget: int = 0
    context_safety_margin: float = 0.85  # зазор 15% на неточность оценки токенов
    context_output_reserve: int = 0  # 0 → берём chat_max_tokens (место под ответ)
    context_prompt_overhead: int = 1000  # системный промпт агента + схемы инструментов
    context_default_window: int = 32768  # окно неизвестной модели (консервативно)
    # Веса секций контекста. Секции, которых нет в запросе, свою долю не получают —
    # веса перенормируются по присутствующим (нет файла → его доля уходит истории).
    context_budget_history: float = 0.30
    context_budget_memory: float = 0.15
    context_budget_plan: float = 0.10
    context_budget_files: float = 0.35  # вложения — это задача, которую ставит юзер
    # База знаний, подмешанная автоматически (модели без function-calling не могут
    # позвать инструмент сами — иначе граф был бы бесполезен на половине каталога).
    context_budget_knowledge: float = 0.15
    context_budget_facts: float = 0.05
    context_budget_summary: float = 0.05
    context_compression_enabled: bool = True  # сжимать крупные источники, а не резать
    compaction_threshold: float = 0.85  # доля usable, при которой авто-компактизация
    # ⚠️ КОМПАКТИЗАЦИЮ ИСТОРИИ РЕШАЕТ BACKEND, НЕ САЙДКАР. Три поля ниже читает он
    # (`compact_context_use_case`, `chat_worker_tasks`), а сюда они объявлены только
    # потому, что `AgentsConfig` имеет `extra="forbid"`: переменные `AGENTS__*` заданы в
    # окружении ОБОИХ сервисов, и незаявленная здесь уронила бы СТАРТ сайдкара.
    #
    # Не удалять как «неиспользуемые»: проверено — они живые, просто у соседа. Тот же
    # случай, что у `whisper_*`/`repo_*` выше. Читает их сайдкар ровно одно —
    # `summary_keep_recent` (`processor_steps`).
    history_summary_enabled: bool = True  # компактизация контекста + саммери в MemOS
    summary_trigger_messages: int = 12
    summary_keep_recent: int = 6
    summary_max_tokens: int = 400
    # Общий дедлайн прогона `/run`. ⚠️ Поднят с 90 с: настройка не читалась нигде, а
    # deep research идёт тем же путём и только опрос LDR бюджетирует 240 с — включение
    # «как объявлено» убило бы его на 90-й секунде. Backend uses the same default
    # and derives its HTTP reader timeout from this deadline plus recovery grace.
    # ⚠️ Поведение удалено, поля — нет. Три настройки ниже не читает никто и из реестра
    # админки они убраны. Поля оставлены, потому что `.env.*` в `.gitignore`: удали поле —
    # и на хосте, где переменная ещё объявлена, `extra="forbid"` не даст СТАРТОВАТЬ.
    token_budget_enabled: bool = True  # DEPRECATED: не читается, оставлено ради старта
    max_context_chars: int = 150_000  # DEPRECATED: не читается, оставлено ради старта
    plan_step_execution_enabled: bool = False  # DEPRECATED: не читается
    # Потолок тела запроса к сайдкару. ⚠️ Поле объявлено ЗДЕСЬ, хотя читает его
    # `contracts.py`: `AgentsConfig` имеет `extra="forbid"`, и переменная
    # `AGENTS__MAX_BODY_BYTES` без объявления роняет СТАРТ обоих сервисов. Ровно так
    # `docker/.env.example` и превращал скопировавшего его в обладателя мёртвого стека.
    max_body_bytes: int = 64 * 1024 * 1024
    run_timeout_sec: float = 570.0

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
