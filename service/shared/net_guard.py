"""Защита от SSRF: хост не должен смотреть внутрь периметра.

Копия ЕСТЬ и у соседнего сервиса — намеренно. Общий пакет ради 45 строк stdlib
связал бы релизы двух сервисов; но и молча разойтись копиям нельзя: отставшая
пропустит адрес, который вторая уже считает внутренним, и это дыра.

Поэтому расхождение ловится не общим кодом, а ОБЩИМИ ВЕКТОРАМИ: у каждой стороны
свой `tests/vectors/net_guard_vectors.json`, и CI суперпроекта сверяет их
побайтово. Правка на одной стороне без второй падает громко, в момент правки.

Кто пользуется: сайдкар — в разборе ссылок (`parse_url`), backend — при скачивании
репозитория для графа знаний (`repo_fetcher`).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket


class UnsafeUrlError(Exception):
    """Raised when a URL resolves to a non-public/internal address (SSRF guard)."""


async def assert_public_host(hostname: str) -> None:
    """Resolve hostname and reject it if any address is private/loopback/link-local/reserved."""
    if not hostname:
        raise UnsafeUrlError("Missing host")
    try:
        infos = await asyncio.get_event_loop().run_in_executor(
            None, socket.getaddrinfo, hostname, None
        )
    except OSError as exc:
        raise UnsafeUrlError(f"Unable to resolve host: {hostname}") from exc
    if not infos:
        raise UnsafeUrlError(f"Unable to resolve host: {hostname}")
    for info in infos:
        raw_addr = info[4][0]
        addr = ipaddress.ip_address(raw_addr.split("%")[0])
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise UnsafeUrlError(f"Host resolves to a non-public address: {hostname} -> {addr}")
