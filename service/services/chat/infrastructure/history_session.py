"""Short-lived history buffer prepared by backend, not persisted sidecar state."""

import asyncio
from datetime import UTC, datetime
from typing import Any


class PseudoSession:
    """In-memory буфер истории на время подготовки запроса.

    Копия доменной сессии без её телеметрии: здесь объект живёт секунды и в сайдкар не
    едет, поэтому мерить его длину незачем.
    """

    def __init__(
        self, session_id: str, ttl_seconds: int | None = None, max_items: int | None = None
    ):
        self.session_id = session_id
        self._items: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._max_items = max_items

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            items = list(self._items)

        if self._ttl is not None:
            cutoff = datetime.now(UTC).timestamp() - self._ttl
            items = [
                it for it in items if float(it.get("ts", datetime.now(UTC).timestamp())) >= cutoff
            ]

        if limit is not None:
            items = items[-limit:]
        return items

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._items.extend(items)
            if self._max_items is not None and len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]

    async def pop_item(self) -> dict[str, Any] | None:
        async with self._lock:
            if not self._items:
                return None
            item = self._items.pop()

        return item

    async def clear_session(self) -> None:
        async with self._lock:
            self._items.clear()
