"""Клиент к ``/tools/*`` сайдкара agents (Фаза 5, снятие зависимости от домена).

У backend есть свои REST-ручки для UI: веб-поиск, разбор ссылки, генерация презентации.
Пока инструменты жили в его дереве, ручки звали их напрямую — и это держало домен
пришпиленным к backend. Теперь инструментами владеет сайдкар.

Почему не продублировали, как клиенты соседних сервисов: это не клиенты, а САМИ
инструменты. У `parse_url` внутри защита от SSRF, у `pptx` — ЛЛМ-вызов; расходиться двум
копиям такого нельзя. Клиент к чужому сервису дублировать дёшево и безопасно, а
реализацию возможности — нет.

Fail-open: сайдкар молчит → backend отрабатывает прежним локальным путём.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from service.infrastructure.sidecar import SidecarBadRequest, SidecarClient, SidecarError

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SEC = 60.0
# Генерация презентации — ЛЛМ-вызов на несколько абзацев плюс сборка файла.
PPTX_TIMEOUT_SEC = 300.0


def _use_sidecar(config: Any) -> bool:
    from service.infrastructure.agents_client.engine_factory import uses_http_engine

    return uses_http_engine(config)


def _client(config: Any, timeout: float) -> SidecarClient:
    agents_cfg = getattr(config, "agents", None)
    return SidecarClient(
        service="agents",
        base_url=str(getattr(agents_cfg, "sidecar_url", "") or ""),
        timeout=timeout,
        api_key=str(getattr(agents_cfg, "llm_gateway_api_key", "") or ""),
    )


async def _post(config: Any, path: str, payload: dict, *, timeout: float) -> dict | None:
    """POST на сайдкар. `None` = не смогли; вызывающий делает локально.

    ⚠️ Fail-open здесь осознанный: у инструментов есть локальный путь, и отказ сайдкара
    не должен лишать пользователя ответа. Но он ЯВНЫЙ, а не встроен в транспорт, и
    «нас отвергли» (4xx) отличается от «сервис лёг» (5xx/сеть) — первое означает, что
    чинить надо у себя.
    """
    try:
        return await _client(config, timeout).request_json("POST", path, json_body=payload)
    except SidecarBadRequest as exc:
        logger.info(
            "agents integration failure",
            extra={"component": "tools", "failure_code": exc.code},
        )
        return None
    except SidecarError:
        logger.warning(
            "agents integration failure",
            extra={"component": "tools", "failure_code": "unavailable"},
        )
        return None


async def web_search(config: Any, query: str, num_results: int = 5) -> list | None:
    if not _use_sidecar(config):
        return None
    data = await _post(
        config,
        "/tools/web-search",
        {"query": query, "num_results": num_results},
        timeout=SEARCH_TIMEOUT_SEC,
    )
    if data is None:
        return None
    results = data.get("results")
    return results if isinstance(results, list) else None


async def parse_url(config: Any, url: str) -> str | None:
    if not _use_sidecar(config):
        return None
    data = await _post(config, "/tools/parse-url", {"url": url}, timeout=SEARCH_TIMEOUT_SEC)
    if data is None:
        return None
    content = data.get("content")
    return content if isinstance(content, str) else None


async def generate_pptx(config: Any, topic: str) -> bytes | None:
    """Презентация в байтах. ``None`` = не смогли, генерируй локально."""
    if not _use_sidecar(config):
        return None
    data = await _post(config, "/tools/pptx", {"topic": topic}, timeout=PPTX_TIMEOUT_SEC)
    if data is None:
        return None
    raw = data.get("pptx_b64")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return base64.b64decode(raw)
    except Exception:  # noqa: BLE001 — битый base64 лучше пересчитать локально
        logger.warning(
            "agents integration failure",
            extra={"component": "tools", "failure_code": "protocol"},
        )
        return None
