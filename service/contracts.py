"""Контракт сайдкара как провайдера: имена, на которые опирается потребитель.

Только stdlib: сверку гоняет офлайн-гейт CI, и тянуть ради двух множеств строк весь
агентный стек он не должен. Производители константы ИМПОРТИРУЮТ — источник правды один.
"""

from __future__ import annotations

# Ключи result-dict `/run`. По ним воркер backend'а списывает деньги и решает, был ли
# ответ. Читает через `.get(...) or 0`: переименование не падает, а тихо даёт ноль.
RESULT_FIELDS = frozenset(
    {
        "reply",
        "metadata",
        "resolved_model",
        "reply_parts_count",
        "reply_chars_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "per_call_usage",
        # Что агент создал в файловой песочнице: [{path, size}]. Пусто/нет ключа — песочницы
        # не было. ⚠️ ОПИСЬ, а не байты: файлы забирает backend, у которого есть хранилище.
        "workspace_artifacts",
    }
)

# Инструменты с фикс-надбавкой. Backend ищет цену через `.get(tool)`, поэтому расхождение
# имён — это молча отключённые деньги: прогон успешен, счёт просто меньше. Сверяет
# `scripts/check_contract_parity.py` с ключами `tool_surcharge_rub` у потребителя.
# `general` не входит: это маркер «инструмент не нужен», а не работа.
BILLABLE_TOOLS = frozenset(
    {
        "web_search",
        "deep_research",
        "image_gen",
        "pptx_gen",
        "pdf_gen",
        "audio_transcribe",
        # Поиск, вызванный МОДЕЛЬЮ внутри обычного ответа. Имя отдельное от маршрутного:
        # совпадение дало бы цену маршрута там, где субагент с синтезом не запускался.
        "web_search_tool",
        # ⚠️ ОДНА запись на весь MCP, а не по серверу и не по инструменту: набор
        # сверяется с прайсом backend'а офлайн-гейтом, и запись на сервер делала бы
        # каждый новый сервер согласованным релизом двух репозиториев.
        "mcp_tool",
        # ⚠️ Тоже ОДНА запись — на все шесть инструментов песочницы, по той же причине.
        "workspace_tool",
        # Просмотр ролика. ⚠️ Надбавка покрывает НЕВИДИМОЕ В ТОКЕНАХ: скачивание, работу
        # ffmpeg и хранение кадров. Сами кадры и расшифровка тарифицируются токенами по
        # своим путям, и вторая цена за них здесь была бы двойным счётом.
        "watch_video",
    }
)

# Historical names remain parseable by backend billing records but are not active
# capabilities. They must not re-enter routing or the compiled capability catalog.
LEGACY_BILLING_NAMES = frozenset({"pptx_gen"})


# --- Виды провайдерских вызовов внутри одного прогона ----------------------------
#
# 🔴 Прогон делает НЕСКОЛЬКО вызовов, часть — служебные, на дешёвой мета-модели. Признак
# «ответила не та модель» строился из любого вызова с моделью ≠ выбранной, и служебная
# декомпозиция зажигала бейдж подмены на честном ответе GigaChat. Бейдж, который врёт,
# хуже отсутствующего.
#
# ⚠️ Словарь ЗАКРЫТЫЙ: каждый эмитируемый `kind` обязан лежать ровно в одном наборе, иначе
# забытый вид молча станет «ответом». Полноту стережёт скан исходников в
# `tests/test_usage_kinds_are_classified.py`. Вызов БЕЗ `kind` — основной поток ответа.

# Служебные: работа ради ответа, но не сам ответ. Модель здесь своя и может отличаться.
SERVICE_USAGE_KINDS = frozenset(
    {
        "route_model",  # выбор модели под запрос
        "meta_usage",  # декомпозиция намерения + сжатие контекста
        "multimodal_usage",  # аналитики модальностей по вложениям
        "image_condense_usage",  # сжатие промпта для генерации картинки
        "pptx_illustration_usage",  # иллюстрации к презентации
        "query_resolution",
        "research_plan",
        "tool_selector",
        "audio_transcription",
        "translation",
        # Mandatory artifact QA is a supporting stage. Its qualified vision
        # model may intentionally differ from the user's authoring model and
        # must not be presented as an answer-provider substitution.
        "document_visual_audit",
    }
)

# Вызовы, породившие текст, который увидел пользователь. Их модель и есть «кто ответил».
ANSWER_USAGE_KINDS = frozenset(
    {
        "chat",
        "multi_intent_usage",  # шаг мульти-интента: его содержимое попадает в ответ
        "empty_response_usage",  # попытка ответа, вернувшая пусто, — тоже попытка ОТВЕТИТЬ
        "research_synthesis",
        "research_repair",
        "audio_postprocess",
        # Artifact-authoring calls produce the user-visible document, even though
        # their text is delivered as a file rather than a chat delta.
        "pdf_authoring",
    }
)

# События без собственных токенов. В `per_call_usage` не попадают.
#
# ⚠️ Виды вложений (`"kind": att.kind` в `pipeline/multimodal.py`) сюда не входят: там
# значение вычисляемое, и событие несёт статус разбора, а не `token_usage`.
NON_USAGE_KINDS = frozenset(
    {
        "multi_intent_artifact",
        "multi_intent_progress",
        "research_progress",
        # Наблюдаемость tool-loop: это состояние исполнения, не вызов модели и не usage.
        "tool_availability",
        "tool_plan",
        "tool_progress",
        "tool_summary",
        "tool_disclosure",
        "tool_intent",
        "integration_health",
        # Токены рассуждения уже посчитаны в `completion` того же вызова
        # (`reasoning_tokens` — подмножество), второй счёт был бы двойным.
        "reasoning",
        "plan_skipped",  # объяснение отказа; плана как раз и не было
        "auto_decision",  # решение оркестратора; его токены уже в `meta_usage`
        "mode_offer",  # дорогой режим НЕ запускался, платить не за что
        # Инструменты, НЕ выданные модели, с причиной на каждый.
        "tool_omissions",
        # Внутреннее наблюдение попадает только в backend-каталог; выполнения в нём нет.
        "workflow_observed",
        # Безопасный факт запуска catalog-workflow; токены/инструменты учтены своими событиями.
        "workflow_execution",
        # Bounded Document Forge stage/outcome projection. Source text, paths and model
        # payloads remain private run state and are never carried by this event.
        "document_status",
        # Bounded workspace pause/resume/cancel state. It is emitted by the
        # run loop, not by a model/provider call, so it must never affect
        # usage aggregation or provider substitution badges.
        "workspace_collaboration",
        # Оркестратор обойдён, маршрут решал прежний роутер. Счётчик для его удаления.
        "legacy_route_used",
    }
)


# ⚠️ Потолок тела запроса. Раньше лимита не было ни у нас, ни у uvicorn (он читает тело
# в память), а в `/run` приезжают история, память и текст вложений — то есть один
# достаточно большой запрос ронял процесс, обслуживающий ВСЕХ. 64 МБ бьют по аномалии:
# backend сам режет текст вложения и историю, файлы едут ссылками.
def _max_body_bytes() -> int:
    """Потолок тела запроса. Из КОНФИГА, а не из `os.environ`.

    ⚠️ При чтении через `os.environ` поля не существовало, и `extra="forbid"` отвергал
    `AGENTS__MAX_BODY_BYTES` — объявить лимит значило уронить старт обоих сервисов.
    """
    from service.settings import config

    return int(config.agents.max_body_bytes)


# ⚠️ ЛЕНИВЫЙ (PEP 562), а не вычисление на импорте. Модуль обязан быть автономным: гейт
# парити грузит его ПО ПУТИ, без пакета `service` на sys.path. Прежний eager-вызов тянул
# `service.settings` на импорте, гейт падал `ModuleNotFoundError` и МОЛЧА не сверял
# контракт (регресс 9f784bb8).
_MAX_BODY_BYTES_CACHE: int | None = None


def __getattr__(name: str) -> object:
    if name == "MAX_BODY_BYTES":
        global _MAX_BODY_BYTES_CACHE
        if _MAX_BODY_BYTES_CACHE is None:
            _MAX_BODY_BYTES_CACHE = _max_body_bytes()
        return _MAX_BODY_BYTES_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Машинные коды ошибок: вызывающий различает случаи по КОДУ, а не по тексту `detail`.
# Раньше в поле `error` лежали фразы вроде «routing failed» — отличить «повтори позже»
# от «поправь запрос» по ним было нельзя.
ERROR_CODES = frozenset(
    {
        "invalid_request",  # 422 — тело не прошло схему
        "not_found",  # 404
        "unauthorized",  # 401
        "engine_unavailable",  # 503 — движок не подан в сайдкар
        "routing_unavailable",  # 503
        "vector_unavailable",  # 503
        "workflow_catalog_unavailable",  # 503
        "media_unavailable",  # 503
        "tool_unavailable",  # 503
        "no_models",  # 503 — ни одной модели у провайдеров
        "topic_required",  # 400
        "request_too_large",  # 413
        "routing_failed",  # 502
        "catalog_failed",  # 502
        "internal",  # 500
    }
)

# ⚠️ `/v1/*` на эту форму НЕ переходит: это чужой протокол (OpenAI), и его клиенты —
# memos, ldr, graphify, сторонние SDK — ждут `{"error": {"message", "type"}}`.
OPENAI_ERROR_PATH_PREFIX = "/v1"

# Поля ответа `/route`. `routing_usage` тарифицируется отдельно, `selected_model` уходит
# в резерв кредитов: потеряется имя — молча потеряются деньги.
ROUTE_RESPONSE_FIELDS = frozenset(
    {
        "selected_model",
        "routing_metadata",
        "web_search",
        "deep_research",
        "route_override",
        "routing_usage",
        "resolved_category",
    }
)
