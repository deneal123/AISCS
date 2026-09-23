"""GigaChat (Сбер): та же фабрика, что у остальных, плюс хуки на его особенности.

GigaChat совместим с OpenAI chat/completions, но отличается по-настоящему, а не
косметически: OAuth2 вместо статичного ключа (см. ``gigachat_auth``), российские
TLS-сертификаты Минцифры и СТАРЫЙ диалект function-calling. Всё это выражено хуками —
остальное (резолв ключа, кэш моделей, пересборка, эмбеддинги) он делит с четвёркой.

⚠️ База НЕ получает дополнительный суффикс `/v1`: актуальный URL уже им оканчивается.
⚠️ В `AsyncOpenAI` едет ЗАГЛУШКА вместо ключа — настоящий Bearer ставит auth-слой на
каждый запрос, но конструктор требует непустой `api_key`. Проверка «настроен ли
провайдер» смотрит при этом на НАСТОЯЩИЙ ключ.
"""

from __future__ import annotations

import logging
import ssl
import time
from typing import Any

import httpx
from openai import AsyncOpenAI

from service.domain.client.protocol.capabilities import GIGACHAT_TOOL_CAPABILITIES
from service.settings import config

from .gigachat_auth import GigaChatAuth, GigaChatTokenManager
from .runtime import ProviderHooks, ProviderRuntime, module_getattr
from .spec import ProviderSpec, settings_value

logger = logging.getLogger(__name__)

DEFAULT_GIGACHAT_TIMEOUT_SEC = 30.0
# Заглушка для AsyncOpenAI: реальный Bearer ставит GigaChatAuth на каждый запрос.
_PLACEHOLDER_KEY = "gigachat-oauth"
_VERIFY_WARNED = False
_CONFIG_ERROR_CODE: str | None = None


class GigaChatTLSConfigError(RuntimeError):
    """Bounded configuration failure; certificate paths never reach diagnostics."""

    reason_code = "tls_config"

    def __init__(self) -> None:
        super().__init__(self.reason_code)


SPEC = ProviderSpec(
    name="gigachat",
    label="GigaChat",
    default_base_url="https://api.giga.chat/v1",
    base_url_suffix=None,  # актуальная база уже оканчивается на /v1
    auto_select_priority=50,
    api_key_field="gigachat_authorization_key",
    base_url_field="gigachat_base_url",
    timeout_field="gigachat_timeout_sec",
    ttl_field="gigachat_models_cache_ttl_sec",
    default_timeout_sec=DEFAULT_GIGACHAT_TIMEOUT_SEC,
    fallback_models=("GigaChat-2", "GigaChat-2-Pro"),
    fallback_model_capabilities=(
        ("GigaChat-2", ("chat", "tools")),
        ("GigaChat-2-Pro", ("chat", "tools")),
    ),
    # Live discovery is authoritative, but GigaChat's /models response does not
    # currently include machine-readable capability metadata.  Keep the evidence
    # exact: only model IDs documented by the provider or observed in the live
    # account catalog are admitted.  An unknown future ID remains fail-closed.
    known_model_capabilities=(
        ("GigaChat-2-Max", ("chat", "tools")),
        ("GigaChat-3-Lightning", ("chat", "tools")),
        ("GigaChat-3-Pro", ("chat", "tools")),
        ("GigaChat-3-Ultra", ("chat", "tools")),
        ("Embeddings", ("embeddings",)),
        ("Embeddings-2", ("embeddings",)),
        ("EmbeddingsGigaR", ("embeddings",)),
        ("GigaEmbeddings-3B-2025-09", ("embeddings",)),
    ),
    embedding_dimensions=(("Embeddings", 1024),),
    require_declared_model_capabilities=True,
    tool_capabilities=GIGACHAT_TOOL_CAPABILITIES,
    # GigaChat присылает usage финальным чанком без request-side `stream_options`.
    # False означает только «не отправлять OpenAI-specific include_usage»; парсер
    # продолжает безусловно учитывать фактически пришедший chunk.usage.
    supports_stream_usage=False,
)

# ⚠️ СТРИМ GIGACHAT НЕ ИНКРЕМЕНТАЛЬНЫЙ — ЭТО СЕРВЕР, А НЕ МЫ. Замерено на трёх уровнях с
# контролем на той же машине и сети: через openai-SDK — одна дельта на весь ответ; сырым
# SSE мимо SDK — 20 событий, но все в один момент; на уровне СЫРЫХ СЕТЕВЫХ БАЙТОВ — 11
# пакетов, первый через 1.66с, последний через 1.68с (весь ответ выгружается за 20 мс
# после паузы на генерацию). Контрольный RouterAI тем же кодом: 582 дельты, растянутые на
# 1.9с. Базовый URL пуст → идём напрямую в Сбер, посредника-буфера нет.
#
# Практический смысл: у GigaChat пользователь видит паузу, а затем ответ целиком. Чинить
# на нашей стороне нечего — не ищите буферизацию в httpx, клиенте или пайплайне, её там
# нет. Единственное, что уместно, — честный индикатор «генерирую» в интерфейсе.

PROVIDER_NAME = SPEC.name


def _build_proxy_url() -> str:
    from service.domain.client.providers._http import build_proxy_url

    return build_proxy_url("gigachat")


def _build_verify() -> Any:
    """Build strict TLS context without leaking certificate paths on failure."""
    global _CONFIG_ERROR_CODE, _VERIFY_WARNED
    _CONFIG_ERROR_CODE = None
    ca_bundle = (config.agents.gigachat_ca_bundle or "").strip()
    if ca_bundle:
        try:
            certificate = ssl._ssl._test_decode_cert(ca_bundle)  # type: ignore[attr-defined]  # noqa: SLF001
            not_before = ssl.cert_time_to_seconds(str(certificate["notBefore"]))
            not_after = ssl.cert_time_to_seconds(str(certificate["notAfter"]))
            if not not_before <= time.time() < not_after:
                raise ValueError("certificate validity window")
            return ssl.create_default_context(cafile=ca_bundle)
        except (KeyError, OSError, TypeError, ValueError, ssl.SSLError):
            _CONFIG_ERROR_CODE = GigaChatTLSConfigError.reason_code
            raise GigaChatTLSConfigError() from None
    if not config.agents.gigachat_verify_ssl:
        if not _VERIFY_WARNED:
            logger.warning(
                "GigaChat TLS verification DISABLED (AGENTS__GIGACHAT_VERIFY_SSL=false). "
                "Set AGENTS__GIGACHAT_CA_BUNDLE to the Mincifry CA chain for production."
            )
            _VERIFY_WARNED = True
        return False
    _CONFIG_ERROR_CODE = GigaChatTLSConfigError.reason_code
    raise GigaChatTLSConfigError() from None


def configuration_error() -> str | None:
    """Return only the bounded provider configuration code for health projection."""
    return _CONFIG_ERROR_CODE


def _gigachat_timeout() -> float:
    return config.agents.gigachat_timeout_sec or DEFAULT_GIGACHAT_TIMEOUT_SEC


_TOKEN_MANAGER: GigaChatTokenManager | None = None


def _reset_token_manager() -> None:
    """Сбросить OAuth-менеджер, чтобы токен перезапросился под новый ключ."""
    global _TOKEN_MANAGER
    _TOKEN_MANAGER = None


def _resolve_authorization_key() -> str:
    """GigaChat authorization_key: runtime-override (админка) иначе env/config.

    ⚠️ РЕЗОЛВИМ ИЗ СПЕКИ, А НЕ ЧЕРЕЗ `_RUNTIME`. Здесь стояло `_RUNTIME.resolve_api_key()`,
    и это роняло инициализацию GigaChat ВСЕГДА, с самого перехода на фабрику:

        ProviderRuntime.__init__ → _build → create_client → make_http_client
        → наш хук _make_http_client → _get_token_manager → сюда → _RUNTIME

    `_RUNTIME` в этот момент ПРИСВАИВАЕТСЯ — имени ещё нет, и получается NameError.
    Хук не может зависеть от рантайма, который его же и конструирует.

    Наружу это выглядело как «GigaChat просто не работает»: `_build` ловит исключение и
    оставляет клиент `None`, сервис поднимается, в логах одна строка `Failed to initialize
    GigaChat client` среди прочего шума при старте. Ни один из 1037 тестов не поймал —
    они зовут хуки уже ПОСЛЕ импорта модуля, когда `_RUNTIME` существует.
    """
    from .credentials import resolve

    default = settings_value(SPEC.api_key_field, *SPEC.api_key_fallback_fields)
    return (resolve(SPEC.name, default) or "").strip()


def _get_token_manager() -> GigaChatTokenManager:
    global _TOKEN_MANAGER
    if _TOKEN_MANAGER is None:
        _TOKEN_MANAGER = GigaChatTokenManager(
            authorization_key=_resolve_authorization_key(),
            scope=config.agents.gigachat_scope,
            oauth_url=config.agents.gigachat_oauth_url,
            verify=_build_verify(),
            timeout=_gigachat_timeout(),
            skew_sec=config.agents.gigachat_token_skew_sec,
            proxy_url=_build_proxy_url(),
        )
    return _TOKEN_MANAGER


def _make_http_client() -> httpx.AsyncClient:
    timeout = _gigachat_timeout()
    proxy_url = _build_proxy_url()
    auth = GigaChatAuth(_get_token_manager())
    kwargs: dict[str, Any] = {"verify": _build_verify(), "timeout": timeout, "auth": auth}
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return httpx.AsyncClient(**kwargs)


def get_openai_client() -> AsyncOpenAI | None:
    return _RUNTIME.client


async def list_available_models(
    client: AsyncOpenAI | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """List models from the GigaChat API (cached, MWS-compatible signature)."""
    return await _RUNTIME.list_available_models(client=client, force_refresh=force_refresh)


async def _chat_completion_legacy(
    target_client: AsyncOpenAI | None,
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    n: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    extra: dict[str, Any] | None = None,
):
    """Chat/completions на СТАРОМ диалекте function-calling.

    Хук фабрики: остальные провайдеры идут общим путём, а GigaChat требует перевода.
    Канонические `tools` он молча игнорирует, а каноническая tool-история
    (`role="tool"` / `assistant.tool_calls`) роняет запрос 422. Стрим-путь это уже
    переводил — здесь его не-стрим близнец (аудит B8).
    """
    if target_client is None:
        raise RuntimeError("GigaChat client is not configured")

    from service.domain.client.protocol import ProviderRunSession, compile_toolset
    from service.domain.client.providers.function_dialect import (
        has_tool_history,
        messages_to_legacy,
        response_to_canonical,
    )

    extra = dict(extra or {})
    tools = extra.pop("tools", None)
    tool_choice = extra.pop("tool_choice", None)
    provider_session = extra.pop("_provider_session", None)
    if not isinstance(provider_session, ProviderRunSession):
        provider_session = None
    send_messages = messages
    if tools or has_tool_history(messages):
        send_messages = messages_to_legacy(
            messages,
            private_state=provider_session.private_state(PROVIDER_NAME)
            if provider_session
            else None,
        )
    if tools:
        compiled = compile_toolset(
            tools,
            provider=PROVIDER_NAME,
            capabilities=SPEC.tool_capabilities,
            tool_choice=tool_choice,
        )
        extra.update(compiled.request_fields())

    payload: dict[str, Any] = {"model": model, "messages": send_messages}
    for key, value in (
        ("temperature", temperature),
        ("max_tokens", max_tokens),
        ("n", n),
        ("presence_penalty", presence_penalty),
        ("frequency_penalty", frequency_penalty),
    ):
        if value is not None:
            payload[key] = value
    if extra:
        payload.update(extra)  # functions/function_call/response_format/top_p/stop/seed/...

    response = await target_client.chat.completions.create(**payload)
    # Ответ старого формата (`function_call`) → канон (`tool_calls`), иначе как есть.
    state_out: dict[str, str] = {}
    canonical = response_to_canonical(
        response,
        call_id=provider_session.next_call_id(provider=PROVIDER_NAME) if provider_session else None,
        private_state_out=state_out if provider_session else None,
    )
    if provider_session and state_out.get("value"):
        provider_session.set_private_state(PROVIDER_NAME, state_out["value"])
    return canonical


async def create_chat_completion(
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    n: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    client: AsyncOpenAI | None = None,
    **extra: Any,
):
    """Call GigaChat chat completions endpoint (/v1/chat/completions)."""
    return await _RUNTIME.chat_completion(
        client,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        extra=extra,
    )


async def create_completion(
    prompt: str,
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    stop: list[str] | None = None,
    client: AsyncOpenAI | None = None,
):
    """GigaChat не имеет /completions — мостим на chat/completions для совместимости."""
    messages = [{"role": "user", "content": prompt}]
    return await create_chat_completion(
        messages,
        model,
        temperature=temperature,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        client=client,
    )


async def create_embedding(
    text: str,
    model: str,
    *,
    client: AsyncOpenAI | None = None,
):
    """Call GigaChat embeddings endpoint (/v1/embeddings)."""
    # Эмбеддинги GigaChat НЕ отличаются от общих: ни OAuth-специфики, ни трансляции
    # диалекта здесь нет.
    return await _RUNTIME.embedding(client, text=text, model=model)


def clear_models_cache() -> None:
    _RUNTIME.models.clear()


def rebuild_client() -> AsyncOpenAI | None:
    """Пересобрать клиента после замены authorization_key (provider_credentials).

    Сброс token-manager делает хук `on_rebuild`: без него висел бы старый Bearer до
    истечения срока, и замена ключа в админке не подействовала бы.
    """
    return _RUNTIME.rebuild()


# ⚠️ Рантайм собирается В КОНЦЕ: его хуки — функции этого модуля, и до их объявления
# конструктор не выполнить. Раньше здесь по той же причине строился `OPENAI_CLIENT`.
_RUNTIME = ProviderRuntime(
    SPEC,
    ProviderHooks(
        http_client_factory=_make_http_client,
        sdk_api_key=lambda: _PLACEHOLDER_KEY,
        chat_completion=_chat_completion_legacy,
        on_rebuild=_reset_token_manager,
    ),
)
__getattr__ = module_getattr(_RUNTIME)
