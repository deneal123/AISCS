"""Декларация провайдера: всё, чем один OpenAI-совместимый отличается от другого.

⚠️ ЗАЧЕМ. Провайдер-модули были почти одинаковы, и знание о том, ЧЕМ именно они
различаются, приходилось выуживать диффом четырёх файлов по 200-270 строк. Различий на
самом деле мало — база, ключ, таймаут, пара заголовков и один флаг про Responses API, —
но каждое было размазано по собственной обвязке.

⚠️ ПОЛЯ НАСТРОЕК УКАЗЫВАЮТСЯ ПО ИМЕНИ, А НЕ ЗНАЧЕНИЕМ. Значение читается в момент
вызова: ключ подменяют из админки, и связанная на импорте копия осталась бы старой —
ровно та беда, что описана в докстринге `active` про `ACTIVE_PROVIDER`.

⚠️ Схлопнуть сами поля `AgentsConfig` в generic-словарь НЕЛЬЗЯ: у настроек стоит
`extra="forbid"`, и незаявленная переменная окружения роняет СТАРТ сервиса. Спека именно
ССЫЛАЕТСЯ на объявленные поля, а не заменяет их.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from service.domain.client.protocol.capabilities import (
    OPENAI_TOOL_CAPABILITIES,
    ProviderToolCapabilities,
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Чем этот провайдер отличается от остальных OpenAI-совместимых."""

    name: str
    """Канонический ключ: им провайдер зовётся в реестре, настройках и трейсе."""

    label: str
    """Человеческое имя для текстов ошибок («OpenRouter client is not configured»)."""

    default_base_url: str
    api_key_field: str
    """Имя поля в `AgentsConfig` — НЕ значение (см. докстринг модуля)."""

    api_key_fallback_fields: tuple[str, ...] = ()
    """Запасные поля ключа. У MWS это `openai_api_key` — наследие прежнего именования."""

    base_url_field: str | None = None
    base_url_fallback_fields: tuple[str, ...] = ()
    timeout_field: str | None = None
    ttl_field: str | None = None

    default_timeout_sec: float = 20.0
    default_ttl_sec: int = 180
    fallback_models: tuple[str, ...] = ()
    fallback_model_capabilities: tuple[tuple[str, tuple[str, ...]], ...] = ()
    known_model_capabilities: tuple[tuple[str, tuple[str, ...]], ...] = ()
    embedding_dimensions: tuple[tuple[str, int], ...] = ()
    require_declared_model_capabilities: bool = False
    """Require an exact local capability profile even for live inventory entries.

    Providers with mixed-purpose catalogs can opt into this fail-closed mode so a
    newly discovered embedding model cannot be inferred to support chat or tools.
    """

    default_headers: tuple[tuple[str, str], ...] = ()
    """Заголовки, которых требует провайдер. OpenRouter — атрибуция (Referer/Title)."""

    base_url_suffix: str | None = "/v1"
    """Чем обязана оканчиваться база. `None` — не дописывать (у GigaChat уже `/v1`)."""

    force_chat_completions_api: bool = True
    """Переключать Agents SDK на chat/completions.

    ⚠️ `False` ТОЛЬКО у нативного OpenAI: он один умеет Responses API. Остальные на
    `/responses` отвечают 404 (у OpenRouter — HTML), и агенты уходили бы в фолбэк.
    """

    requires_base_url: bool = False
    """База обязательна, а не только ключ. У MWS без неё клиент бессмыслен."""

    auto_select_priority: int = 100
    """Порядок перебора в режиме `llm_provider=auto`: меньше — раньше.

    ⚠️ Раньше это была if/elif цепочка в `active`, продублированная ВТОРОЙ цепочкой для
    явного выбора. Добавляя провайдера, надо было вписать себя в обе, и пропуск одной
    давал провайдера, которого нельзя выбрать, — без единой ошибки.
    """

    auto_select_fields: tuple[str, ...] = ()
    """Поля настроек, любое из которых делает провайдера пригодным для авто-выбора.

    Пусто → берётся `api_key_field`. У MWS и OpenAI сюда входит ещё и база: это
    self-hosted шлюзы, где ключ бывает пустым, а адрес задан.
    """

    supports_stream_usage: bool = False
    """Понимает ли `stream_options.include_usage` в стриме.

    ⚠️ ДЕНЕЖНЫЙ ФЛАГ. У кого True — провайдер сам присылает usage финальным чанком, и мы
    биллим по факту. У кого False запрос этого поля может отклонить ВЕСЬ стрим, поэтому
    учёт деградирует на оценку. Раньше знание жило отдельным множеством в `streaming`, и
    провайдер, забытый там, молча терял бы точный учёт.

    ⚠️ GigaChat оставляет значение `False` намеренно: его актуальный контракт не объявляет
    OpenAI-specific `stream_options`, а фактический usage он присылает без request-side
    флага. Парсер всегда поглощает пришедший `chunk.usage`, поэтому точный учёт от этого
    значения не зависит. У MWS `False` означает «не проверено»: доступный ключ отвечает 401.
    """

    tool_capabilities: ProviderToolCapabilities = OPENAI_TOOL_CAPABILITIES
    """Типизированный tool protocol, schema profile и round semantics провайдера."""

    strip_api_key: bool = True
    """Обрезать ли пробелы у ключа.

    ⚠️ У MWS исторически НЕ обрезается. Разница ничего не значит по смыслу, но менять её
    заодно с переносом — значит смешать рефакторинг с правкой поведения.
    """

    extra_settings_fields: tuple[str, ...] = field(default=())
    """Прочие поля настроек, принадлежащие провайдеру, — для сверки со спеками."""

    def __post_init__(self) -> None:
        """Reject ambiguous cold-start capability declarations at import time."""
        fallback_names = set(self.fallback_models)
        profile_names = [model for model, _ in self.fallback_model_capabilities]
        if len(profile_names) != len(set(profile_names)):
            raise ValueError("duplicate fallback model capability profile")
        if set(profile_names) != fallback_names:
            raise ValueError("fallback models require exact capability profiles")
        known_names = [model for model, _ in self.known_model_capabilities]
        if len(known_names) != len(set(known_names)):
            raise ValueError("duplicate known model capability profile")
        allowed = {
            "chat",
            "tools",
            "vision",
            "image_output",
            "embeddings",
            "transcription",
        }
        for model, capabilities in (
            *self.fallback_model_capabilities,
            *self.known_model_capabilities,
        ):
            values = set(capabilities)
            if not values or not values <= allowed:
                raise ValueError(f"invalid fallback capabilities for {model}")
            if ("tools" in values or "vision" in values) and "chat" not in values:
                raise ValueError(f"fallback capability requires chat for {model}")
        dimensions = [model for model, _ in self.embedding_dimensions]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("duplicate embedding dimension profile")
        for model, dimension in self.embedding_dimensions:
            if int(dimension) <= 0 or "embeddings" not in self.capabilities_for_model(model):
                raise ValueError("embedding dimension requires an embeddings profile")

    def fallback_capabilities(self, model: str) -> frozenset[str]:
        """Return explicitly declared capabilities for a cold-start fallback."""
        for model_id, capabilities in self.fallback_model_capabilities:
            if model_id == model:
                return frozenset(capabilities)
        return frozenset()

    def capabilities_for_model(self, model: str) -> frozenset[str]:
        """Return exact local evidence for a discovered or fallback model."""

        for model_id, capabilities in (
            *self.fallback_model_capabilities,
            *self.known_model_capabilities,
        ):
            if model_id == model:
                return frozenset(capabilities)
        return frozenset()

    def embedding_dimension_for(self, model: str) -> int | None:
        for model_id, dimension in self.embedding_dimensions:
            if model_id == model:
                return int(dimension)
        return None


def settings_value(spec_field: str | None, *fallbacks: str) -> object | None:
    """Значение поля настроек по ИМЕНИ, с запасными полями. Читается при вызове."""
    from service.settings import config

    for name in (spec_field, *fallbacks):
        if not name:
            continue
        value = getattr(config.agents, name, None)
        if value:
            return value
    return None
