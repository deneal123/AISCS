"""Фабрика провайдера: одна реализация обвязки на всех OpenAI-совместимых.

Собирает по :class:`ProviderSpec` то, что раньше было скопировано в каждый клиент:
резолв ключа и базы, HTTP-клиент с прокси, создание `AsyncOpenAI`, привязку дефолтов
Agents SDK, пересборку после замены ключа и кэш моделей.

⚠️ СОСТОЯНИЕ ЖИВЁТ ЗДЕСЬ, А НЕ В МОДУЛЕ ПРОВАЙДЕРА. Раньше каждый клиент держал свои
`OPENAI_CLIENT`/`OPENAI_API_KEY` и переписывал их через `global` в `rebuild_client`. Тот,
кто прочитал бы их значением (`from mws_client import OPENAI_CLIENT`), навсегда остался
бы со старым клиентом — та же ловушка, что описана в `active` про `ACTIVE_PROVIDER`.
Здесь состояние — атрибуты объекта, а модуль отдаёт их через `module_getattr`, то есть
ЖИВЫМИ по построению: устареть нечему.

⚠️ ПОЧЕМУ МОДУЛЬ НЕ СТАЛ ЧИСТЫМ ПРОКСИ. `__getattr__` модуля (PEP 562) срабатывает
только на доступ ЧЕРЕЗ АТРИБУТ. Голое имя внутри функции самого модуля разрешается по
`__dict__` и до `__getattr__` не доходит — проверено, получается `NameError`. Поэтому
функции провайдера остаются явными и обращаются к рантайму, а прокси отдаёт только
состояние, которое читают снаружи.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import httpx
from openai import AsyncOpenAI

from service.domain.client.model_catalog import ProviderModelCatalog
from service.domain.client.provider_generation import (
    ProviderGenerationLease,
    ProviderGenerationManager,
)

from ._sdk import (
    set_default_openai_api,
    set_default_openai_client,
    set_default_openai_key,
    set_tracing_disabled,
)
from .model_list_cache import ModelListCache
from .spec import ProviderSpec, settings_value

logger = logging.getLogger(__name__)

# Имена состояния, которые провайдер-модуль отдаёт наружу. Читаются реестром, фасадом,
# health, media, vector_store и шлюзом — девять мест прода.
STATE_NAMES = ("OPENAI_CLIENT", "OPENAI_API_KEY", "BASE_URL")


@dataclass(frozen=True)
class ProviderHooks:
    """Экзотика одного провайдера, которую не выразить декларацией.

    ⚠️ У обычного провайдера хуков НЕТ ВОВСЕ — и это главное свойство. Всё, что можно
    описать значениями (база, поля настроек, заголовки, флаги), живёт в спеке; сюда
    попадает только то, для чего нужен код: OAuth, чужой TLS, другой диалект вызова
    инструментов. Сегодня это ровно один провайдер — GigaChat.
    """

    http_client_factory: Callable[[], httpx.AsyncClient] | None = None
    """Свой HTTP-клиент. У GigaChat это TLS с CA-бандлом Минцифры плюс OAuth-auth."""

    sdk_api_key: Callable[[], str] | None = None
    """Что отдать в `AsyncOpenAI` вместо ключа.

    ⚠️ У GigaChat это ЗАГЛУШКА: настоящий Bearer ставит auth-слой на каждый запрос, но
    `AsyncOpenAI` требует непустой `api_key`. Проверка «провайдер настроен» при этом
    смотрит на НАСТОЯЩИЙ ключ — иначе заглушка делала бы её всегда-истинной.
    """

    chat_completion: Callable[..., Awaitable[Any]] | None = None
    """Свой путь chat/completions. У GigaChat — трансляция старого диалекта."""

    on_rebuild: Callable[[], None] | None = None
    """Что сбросить при пересборке. У GigaChat — token-manager, иначе висит старый Bearer."""


class ProviderRuntime:
    """Живое состояние одного провайдера плюс вся его обвязка."""

    def __init__(self, spec: ProviderSpec, hooks: ProviderHooks | None = None):
        self.spec = spec
        self.hooks = hooks or ProviderHooks()
        self.models = ModelListCache(
            name=spec.label,
            provider=spec.name,
            ttl_fn=self._models_cache_ttl,
            fallback=list(spec.fallback_models),
            capability_profiles=(
                *spec.fallback_model_capabilities,
                *spec.known_model_capabilities,
            ),
            embedding_dimensions=spec.embedding_dimensions,
        )
        self.api_key: str = ""
        self.sdk_api_key: str = ""
        self.base_url: str = ""
        self.client: AsyncOpenAI | None = None
        self.generations = ProviderGenerationManager(spec.name)
        self._build()

    # --- чтение настроек -------------------------------------------------- #
    def resolve_api_key(self) -> str:
        """Ключ: runtime-override из админки, иначе поля настроек по порядку."""
        from .credentials import resolve

        default = settings_value(self.spec.api_key_field, *self.spec.api_key_fallback_fields)
        raw = resolve(self.spec.name, default) or ""
        return raw.strip() if self.spec.strip_api_key else raw

    def resolve_base_url(self) -> str:
        raw = str(
            settings_value(self.spec.base_url_field, *self.spec.base_url_fallback_fields) or ""
        ).strip()
        base = (raw or self.spec.default_base_url).rstrip("/")
        if not base:
            return ""
        suffix = self.spec.base_url_suffix
        if suffix and not base.endswith(suffix):
            base = f"{base}{suffix}"
        return base

    def _models_cache_ttl(self) -> int:
        ttl = settings_value(self.spec.ttl_field) or self.spec.default_ttl_sec
        return max(1, int(ttl))

    def make_http_client(self) -> httpx.AsyncClient:
        from . import openai_compatible

        if self.hooks.http_client_factory is not None:
            return self.hooks.http_client_factory()
        timeout = settings_value(self.spec.timeout_field) or self.spec.default_timeout_sec
        return openai_compatible.make_http_client(self.spec.name, float(timeout))

    # --- жизненный цикл клиента ------------------------------------------- #
    def create_client(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        bind_sdk: bool = True,
    ) -> AsyncOpenAI | None:
        spec = self.spec
        api_key = self.resolve_api_key() if api_key is None else api_key
        base_url = self.resolve_base_url() if base_url is None else base_url

        if not api_key or (spec.requires_base_url and not base_url):
            missing = f"AGENTS__{spec.api_key_field.upper()}"
            if spec.requires_base_url and spec.base_url_field:
                missing += f" or AGENTS__{spec.base_url_field.upper()}"
            logger.warning("%s client is not configured: missing %s", spec.label, missing)
            return None

        # ⚠️ SDK получает НЕ обязательно тот же ключ: у GigaChat туда едет заглушка,
        # потому что настоящий Bearer ставит auth-слой на каждый запрос. Проверка выше
        # при этом смотрит на настоящий ключ — иначе она была бы всегда-истинной.
        sdk_key = self.hooks.sdk_api_key() if self.hooks.sdk_api_key else api_key
        try:
            client = AsyncOpenAI(
                api_key=sdk_key,
                # Пустая база — это НЕ пустая строка, а `None`: SDK тогда берёт свой
                # дефолт. Так устроен нативный OpenAI, у которого базы обычно нет.
                base_url=base_url or None,
                http_client=self.make_http_client(),
                default_headers=dict(spec.default_headers) or None,
            )
            if bind_sdk:
                self._bind_sdk(client, sdk_key)
            return client
        except Exception:
            logger.error("provider client initialization failed code=internal")
            return None

    def _bind_sdk(self, client: AsyncOpenAI, sdk_key: str) -> None:
        self.sdk_api_key = sdk_key
        set_default_openai_key(sdk_key)
        set_default_openai_client(client)
        if self.spec.force_chat_completions_api:
            set_default_openai_api("chat_completions")
        set_tracing_disabled(disabled=True)

    def _build(self) -> None:
        self.api_key = self.resolve_api_key()
        self.base_url = self.resolve_base_url()
        try:
            self.client = self.create_client()
        except Exception:  # noqa: BLE001 — провайдер без клиента не должен ронять импорт
            logger.error("provider client initialization failed code=internal")
            self.client = None
        self.generations.publish(
            client=self.client,
            configuration_digest=self._configuration_digest(self.api_key, self.base_url),
        )

    def rebuild(self) -> AsyncOpenAI | None:
        """Пересобрать после замены ключа в админке; кэш моделей сбрасывается."""
        if self.hooks.on_rebuild is not None:
            self.hooks.on_rebuild()
        self._build()
        self.models.clear()
        return self.client

    async def rebuild_generation(self) -> AsyncOpenAI | None:
        """Prepare client and catalog before publishing the next runtime generation."""

        api_key = self.resolve_api_key()
        base_url = self.resolve_base_url()
        digest = self._configuration_digest(api_key, base_url)
        candidate: AsyncOpenAI | None = None
        try:
            if self.hooks.on_rebuild is not None:
                self.hooks.on_rebuild()
            candidate = self.create_client(
                api_key=api_key,
                base_url=base_url,
                bind_sdk=False,
            )
            self.models.clear()
            catalog = (
                await self.models.get_snapshot(
                    client=candidate,
                    force_refresh=True,
                    configuration_key=digest,
                )
                if candidate is not None
                else None
            )
            if candidate is not None:
                sdk_key = self.hooks.sdk_api_key() if self.hooks.sdk_api_key else api_key
                self._bind_sdk(candidate, sdk_key)
            else:
                self.sdk_api_key = ""
        except BaseException:
            self.models.clear()
            self.api_key = api_key
            self.base_url = base_url
            self.client = None
            self.sdk_api_key = ""
            self.generations.discard_unpublished(candidate)
            self.generations.publish(
                client=None,
                configuration_digest=digest,
            )
            logger.error("provider generation rebuild failed code=internal")
            raise

        self.api_key = api_key
        self.base_url = base_url
        self.client = candidate
        self.generations.publish(
            client=candidate,
            configuration_digest=digest,
            catalog=catalog,
        )
        return candidate

    # --- вызовы ------------------------------------------------------------ #
    async def list_available_models(
        self, client: AsyncOpenAI | None = None, force_refresh: bool = False
    ) -> list[str]:
        snapshot = await self.model_catalog(client=client, force_refresh=force_refresh)
        return list(snapshot.models)

    async def model_catalog(
        self,
        client: AsyncOpenAI | None = None,
        force_refresh: bool = False,
        configuration_key: str | None = None,
    ) -> ProviderModelCatalog:
        """Return the provider inventory with source/freshness information."""
        return await self.models.get_snapshot(
            client=client or self.client,
            force_refresh=force_refresh,
            configuration_key=configuration_key or self._catalog_configuration_key(),
        )

    def _catalog_configuration_key(self) -> str:
        """Hash live connection identity without retaining or exposing credentials."""
        return self._configuration_digest(self.resolve_api_key(), self.resolve_base_url())

    def _configuration_digest(self, api_key: str, base_url: str) -> str:
        material = "\0".join((self.spec.name, api_key, base_url))
        return sha256(material.encode("utf-8")).hexdigest()

    def catalog_configuration_generation(self) -> str:
        """Return a safe identity for cache/run invalidation without exposing secrets."""

        return self._catalog_configuration_key()

    def acquire_generation(self) -> ProviderGenerationLease:
        """Lease the exact client generation visible to a new run."""

        return self.generations.acquire()

    def attach_generation_catalog(
        self,
        sequence: int,
        catalog: ProviderModelCatalog,
    ) -> bool:
        """Make refreshed evidence visible only to leases acquired afterwards."""

        return self.generations.attach_catalog(sequence=sequence, catalog=catalog)

    async def drain_generations(self) -> None:
        """Await closure of retired clients during application shutdown."""

        await self.generations.drain()

    async def chat_completion(self, client: AsyncOpenAI | None, **kw: Any):
        from . import openai_compatible

        if self.hooks.chat_completion is not None:
            return await self.hooks.chat_completion(client or self.client, **kw)
        return await openai_compatible.chat_completion(client or self.client, self.spec.label, **kw)

    async def completion(self, client: AsyncOpenAI | None, **kw: Any):
        from . import openai_compatible

        return await openai_compatible.completion(client or self.client, self.spec.label, **kw)

    async def embedding(self, client: AsyncOpenAI | None, **kw: Any):
        from . import openai_compatible

        return await openai_compatible.embedding(client or self.client, self.spec.label, **kw)

    # --- состояние наружу --------------------------------------------------- #
    def state(self, name: str) -> Any:
        """Значение имени из :data:`STATE_NAMES` — всегда живое."""
        if name == "OPENAI_CLIENT":
            return self.client
        if name == "OPENAI_API_KEY":
            # Именно SDK-ключ: у GigaChat наружу смотрит заглушка, как и раньше.
            return self.sdk_api_key
        if name == "BASE_URL":
            return self.base_url
        raise AttributeError(name)


def module_getattr(runtime: ProviderRuntime):
    """`__getattr__` для модуля провайдера: отдаёт состояние живым.

    ⚠️ На неизвестное имя ОБЯЗАН бросать `AttributeError`. От этого зависит
    `active.get_openai_client`, который проверяет наличие метода через `hasattr`:
    молчаливый `None` сделал бы проверку всегда-истинной.
    """

    def _getattr(name: str) -> Any:
        if name in STATE_NAMES:
            return runtime.state(name)
        raise AttributeError(f"module has no attribute {name!r}")

    return _getattr
