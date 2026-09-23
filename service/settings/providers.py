"""Провайдеры LLM: ключи, адреса, прокси, порядок фейловера и ретраи.

Секция отделена, потому что растёт по своему поводу — с каждым новым провайдером, — и её
объём не должен упираться в потолок соседних тем.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProviderSettings(BaseModel):
    """Поля провайдеров. Собирается в `AgentsConfig`, отдельно не читается."""

    llm_provider: str = "auto"
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
    routerai_base_url: str = Field(default_factory=str)
    routerai_timeout_sec: float = 45.0
    routerai_models_cache_ttl_sec: int = 180
    # --- Whisper.cpp (локальная STT через сайдкар) ---
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
    llm_retry_base_delay_sec: float = 0.4
    llm_retry_max_delay_sec: float = 4.0

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
        if provider not in {"auto", "mws", "openai", "openrouter", "gigachat", "routerai"}:
            return "auto"
        return provider

    @field_validator("gigachat_scope", mode="before")
    @classmethod
    def _normalize_gigachat_scope(cls, value):
        scope = str(value or "GIGACHAT_API_PERS").strip().upper()
        if scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_CORP", "GIGACHAT_API_B2B"}:
            return "GIGACHAT_API_PERS"
        return scope
