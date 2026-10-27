"""Особенности ответа обрабатывает адаптер, не глобальный разбор произвольного JSON."""

from service.domain.client.registry import get_provider_module


def normalize(provider, response):
    adapter = get_provider_module(provider)
    handler = getattr(adapter, "normalize_embedding_response", None)
    return handler(response) if callable(handler) else response
