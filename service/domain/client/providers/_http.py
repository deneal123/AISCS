"""Общие HTTP-хелперы для провайдер-модулей.

Единая точка построения прокси-URL с per-provider allowlist: прокси нужен только
зарубежным провайдерам (openrouter/openai — заблокированы в РФ), а российские
(routerai/gigachat/mws) доступны напрямую и через зарубежный прокси НЕ достаются.
Список — `AGENTS__PROXY_PROVIDERS` (CSV). Решение фиксируется при импорте клиентов.
"""

from __future__ import annotations

from service.settings import config


def _proxy_enabled_for(provider: str) -> bool:
    raw = getattr(config.agents, "proxy_providers", "") or ""
    allow = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return provider.strip().lower() in allow


def build_proxy_url(provider: str) -> str:
    """http-proxy URL для ``provider`` или ``""`` — если провайдер не в
    ``AGENTS__PROXY_PROVIDERS`` либо прокси не сконфигурирован."""
    if not _proxy_enabled_for(provider):
        return ""
    host = (config.agents.proxy_host or "").strip()
    if not host or not config.agents.proxy_port:
        return ""
    user = (config.agents.proxy_user or "").strip()
    password = (config.agents.proxy_pass or "").strip()
    if user or password:
        return f"http://{user}:{password}@{host}:{config.agents.proxy_port}"
    return f"http://{host}:{config.agents.proxy_port}"
