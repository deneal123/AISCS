"""Legacy vision-pool filtering, separate from provider registration/admission."""

import logging

logger = logging.getLogger(__name__)


async def keep_same_modality(models: list[str], prefer: str) -> list[str]:
    from .registry import is_chat_capable

    try:
        from service.shared.model_catalog import get_openrouter_catalog, model_has_capability

        catalog = await get_openrouter_catalog()
        if not model_has_capability(prefer, "vision", catalog):
            return models
        seeing = [
            m for m in models if model_has_capability(m, "vision", catalog) and is_chat_capable(m)
        ]
    except Exception:  # noqa: BLE001 — unknown capability is not evidence
        logger.debug("model catalog unavailable", extra={"failure_code": "unavailable"})
        return []
    if not seeing:
        logger.warning("У провайдера нет зрячей замены для '%s' — провайдер пропущен", prefer)
    return seeing
