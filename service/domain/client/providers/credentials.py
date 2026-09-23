"""Runtime-переопределение API-ключей провайдеров.

Источник истины по-прежнему env/``config.agents.*_api_key``. Этот слой лишь
кладёт поверх него per-provider override, задаваемый из админки (замена ключа без
рестарта стека). Провайдер-фабрики (``create_*_client``) читают ключ через
:func:`resolve`, поэтому пока override не задан — поведение идентично прежнему
(фабрика получает config-дефолт). После :func:`set_override` нужно пересобрать
клиента провайдера (см. ``client.rebuild_provider``), т.к. ``AsyncOpenAI``
строится один раз.

Хранилище — процесс-локальный словарь. Персистентность и синхронизация между
воркерами обеспечиваются БД (``provider_secrets``) + гидрацией при старте.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# provider name -> API key (runtime override). Пусто до первой замены/гидрации.
_overrides: dict[str, str] = {}


def resolve(provider: str, default: str | None) -> str | None:
    """Ключ провайдера: runtime-override (если задан непустым) иначе config-дефолт."""
    override = _overrides.get(provider)
    return override if override else default


def set_override(provider: str, key: str) -> None:
    """Задать/заменить runtime-ключ провайдера (без пересборки клиента — см. модуль)."""
    if key:
        _overrides[provider] = key
        logger.info("provider credential override set: %s", provider)


def clear_override(provider: str) -> None:
    """Убрать runtime-ключ провайдера → возврат к env/config-дефолту."""
    if _overrides.pop(provider, None) is not None:
        logger.info("provider credential override cleared: %s", provider)


def get_override(provider: str) -> str | None:
    """Текущий runtime-ключ провайдера (или None). Для сравнения при ре-гидрации."""
    return _overrides.get(provider)
