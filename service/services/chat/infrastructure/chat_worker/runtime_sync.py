"""Best-effort synchronization of process-local worker configuration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def sync_provider_keys() -> None:
    """Refresh provider credentials before an LLM call without blocking chat."""

    try:
        from service.services.admin.application.provider_key_service import ProviderKeyService

        await ProviderKeyService().sync_if_changed()
    except Exception:
        logger.debug("provider key sync skipped", extra={"failure_code": "unavailable"})


def bind_runtime_settings(pg_connector: Any) -> None:
    """Bind the admin snapshot repository once for this worker process."""

    try:
        from service.services.admin.application.runtime_settings import runtime_settings
        from service.services.admin.persistence.app_settings_repository import (
            AppSettingsRepository,
        )

        runtime_settings.ensure_bound(lambda: AppSettingsRepository(pg_connector))
    except Exception:
        logger.debug(
            "runtime_settings bind in worker failed",
            extra={"failure_code": "unavailable"},
        )


__all__ = ["bind_runtime_settings", "sync_provider_keys"]
