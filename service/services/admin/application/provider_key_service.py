"""Runtime-управление API-ключами провайдеров (замена без рестарта стека).

Координирует: шифр-хранилище (``provider_secrets``) ↔ процесс-локальный override
(``provider_credentials``) ↔ пересборку клиента (``client.rebuild_provider``).
Ключи наружу НИКОГДА не отдаются — только статус «настроен/дата».

Мульти-процессность (backend + celery-воркеры — разные процессы со своими
клиентами): БД — источник истины; при каждой замене инкрементим Redis-счётчик
версии, а процессы дёшево сверяют его (:meth:`sync_if_changed`) и при изменении
ре-гидрируют ключи из БД + пересобирают клиентов. При старте — :meth:`hydrate_all`.
"""

from __future__ import annotations

import logging
from typing import Any

from service.services.admin.persistence.provider_secrets_repository import (
    ProviderSecretsRepository,
)
from service.settings import config
from service.shared.security.secret_cipher import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

# Провайдеры, чей ключ можно заменять из админки (совпадает с PROVIDER_MODULES).
PROVIDERS: tuple[str, ...] = ("openai", "openrouter", "routerai", "mws", "gigachat")
_VERSION_KEY = "provider_keys:version"

# Версия ключей, применённая В ЭТОМ процессе (для дешёвой сверки с Redis).
_applied_version = -1


def _env_key(provider: str) -> str:
    """Ключ провайдера из окружения/config (без учёта override)."""
    a = config.agents
    return {
        "openai": a.openai_api_key,
        "openrouter": a.openrouter_api_key,
        "routerai": a.routerai_api_key,
        "mws": a.mws_api_key or a.openai_api_key,
        "gigachat": a.gigachat_authorization_key,
    }.get(provider, "") or ""


class ProviderKeyService:
    """Замена/удаление/статус провайдерских API-ключей в рантайме."""

    def __init__(self, repo: ProviderSecretsRepository | None = None) -> None:
        if repo is None:
            from service.infrastructure.database.postgresql import PgConnector

            repo = ProviderSecretsRepository(PgConnector(config.pg))
        self._repo = repo

    # --- запись -----------------------------------------------------------------
    async def set_key(
        self, provider: str, api_key: str, *, updated_by: str | None
    ) -> dict[str, Any]:
        provider = self._validate(provider)
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("empty api key")
        await self._repo.upsert(
            provider=provider, secret_enc=encrypt_secret(api_key), updated_by=updated_by
        )
        await self._bump_version()
        # Довести до сайдкара СРАЗУ: иначе замена ключа в панели «не действует» до
        # следующего чат-сообщения (а то и вовсе — если воркер не перезапрашивал версию).
        await self.ensure_sidecar_keys()
        logger.info("provider key replaced at runtime: %s (by %s)", provider, updated_by)
        return await self._status_one(provider)

    async def delete_key(self, provider: str, *, updated_by: str | None) -> dict[str, Any]:
        provider = self._validate(provider)
        await self._repo.delete(provider=provider)
        await self._bump_version()
        # Довести до сайдкара СРАЗУ: иначе замена ключа в панели «не действует» до
        # следующего чат-сообщения (а то и вовсе — если воркер не перезапрашивал версию).
        await self.ensure_sidecar_keys()
        logger.info("provider key override removed: %s (by %s)", provider, updated_by)
        return await self._status_one(provider)

    # --- чтение -----------------------------------------------------------------
    async def list_status(self) -> list[dict[str, Any]]:
        stored = await self._safe_get_all()
        return [self._status_row(p, stored.get(p)) for p in PROVIDERS]

    # --- синхронизация процессов ------------------------------------------------
    async def hydrate_all(self) -> int:
        """Довести ключи из БД до САЙДКАРА (он единственный, кто ими пользуется).

        Раньше метод применял override'ы в СВОЁМ процессе и пересобирал локальные
        клиенты. После выноса движка это чинило клиент, которым уже никто не звонит:
        LLM-вызовы делает сайдкар, а PG/Redis у него нет. Возвращает 1, если снимок
        доставлен, иначе 0 — прежний контракт «число изменённых» здесь смысла не имеет.
        """
        return 1 if await self.ensure_sidecar_keys() else 0

    async def sync_if_changed(self) -> bool:
        """Дёшево (один Redis GET) сверить версию ключей; при изменении — ре-гидрация.

        Вызывается на входе воркер-задачи. Смысл сместился: раньше «подхватить замену
        в своём процессе», теперь — «убедиться, что замену получил САЙДКАР»."""
        global _applied_version
        try:
            client = self._redis()
            raw = await client.get(_VERSION_KEY)
        except Exception:
            return False
        version = int(raw) if raw is not None else 0
        await self.ensure_sidecar_keys(version)
        if version == _applied_version:
            return False
        try:
            await self.hydrate_all()
        except Exception:
            logger.debug("provider keys hydrate failed during sync", exc_info=True)
            return False
        _applied_version = version
        return True

    async def ensure_sidecar_keys(self, version: int | None = None) -> bool:
        """Довести ключи до САЙДКАРА, если движок исполняется там.

        После флипа LLM-вызовы делает сайдкар, а PG/Redis у него нет — ре-гидрация в
        воркере чинит клиент, которым уже никто не звонит. Пушим снимок при расхождении
        версий; расхождение возникает и после РЕСТАРТА сайдкара (он теряет override'ы и
        откатывается к ключам из env — ровно тот случай, когда «заменил ключ в панели, а
        не помогло»).

        Fail-soft: недоступен сайдкар — залогируем и пойдём дальше, чат важнее.
        """
        from service.infrastructure.agents_client.engine_factory import uses_http_engine

        if not uses_http_engine(config):
            return False
        from service.infrastructure.agents_client.sidecar_providers import (
            fetch_keys_version,
            push_provider_keys,
        )

        try:
            if version is None:
                raw = await self._redis().get(_VERSION_KEY)
                version = int(raw) if raw is not None else 0
        except Exception:  # noqa: BLE001
            version = 0

        remote = await fetch_keys_version(config)
        if remote is not None and remote == version:
            return False  # сайдкар уже на этой версии — не гоняем секреты зря

        overrides: dict[str, str] = {}
        try:
            stored = await self._safe_get_all()
            for provider in PROVIDERS:
                row = stored.get(provider)
                if row and row.get("secret_enc"):
                    overrides[provider] = decrypt_secret(row["secret_enc"])
        except Exception:  # noqa: BLE001
            logger.warning("не собрали override'ы ключей для сайдкара", exc_info=True)
            return False

        return await push_provider_keys(config, version=version, overrides=overrides)

    # --- внутреннее -------------------------------------------------------------
    def _redis(self):
        from service.infrastructure.cache.redis_manager import RedisManager

        return RedisManager(config.redis).get_client()

    async def _bump_version(self) -> None:
        global _applied_version
        try:
            version = int(await self._redis().incr(_VERSION_KEY))
            _applied_version = version  # этот процесс уже применил изменение локально
        except Exception:
            logger.debug("provider keys version bump failed (redis)", exc_info=True)

    @staticmethod
    def _validate(provider: str) -> str:
        norm = (provider or "").strip().lower()
        if norm not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider!r}")
        return norm

    async def _safe_get_all(self) -> dict[str, dict[str, Any]]:
        try:
            return await self._repo.get_all()
        except Exception:
            logger.debug("provider secrets get_all failed", exc_info=True)
            return {}

    async def _status_one(self, provider: str) -> dict[str, Any]:
        stored = await self._safe_get_all()
        return self._status_row(provider, stored.get(provider))

    @staticmethod
    def _status_row(provider: str, row: dict[str, Any] | None) -> dict[str, Any]:
        has_override = row is not None
        has_env = bool(_env_key(provider))
        updated_at = row.get("updated_at") if row else None
        return {
            "provider": provider,
            # ключ задан из админки (лежит в БД, перекрывает env)
            "has_override": has_override,
            # ключ присутствует в окружении/config
            "has_env": has_env,
            # провайдер имеет какой-либо ключ (готов к работе по ключу)
            "configured": has_override or has_env,
            "source": "override" if has_override else ("env" if has_env else "none"),
            "updated_at": updated_at.isoformat()
            if hasattr(updated_at, "isoformat")
            else updated_at,
            "updated_by": row.get("updated_by") if row else None,
        }
