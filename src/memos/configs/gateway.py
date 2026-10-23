"""Допуск профилей GPTHub; обычный самостоятельный MemOS остаётся совместимым."""

import os

from urllib.parse import urlsplit


def managed_memory_enabled():
    explicit = os.getenv("MOS_MULTIPROVIDER_ENABLED")
    if explicit is not None:
        return explicit.lower() == "true"
    endpoint = urlsplit(os.getenv("MOS_EMBEDDER_API_BASE", ""))
    return endpoint.hostname == "agents" and endpoint.path.rstrip("/") == "/v1"
