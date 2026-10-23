"""Содержимое памяти и ключи не попадают в отладочные сообщения HTTP/SDK."""

from contextlib import contextmanager
from contextvars import ContextVar
from logging import Filter, getLogger


_PRIVATE = ContextVar("private_memory_transport", default=False)


class _Filter(Filter):
    def filter(self, record):
        return not _PRIVATE.get()


for _name in (
    "openai._base_client",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
):
    getLogger(_name).addFilter(_Filter())


@contextmanager
def private_transport():
    token = _PRIVATE.set(True)
    try:
        yield
    finally:
        _PRIVATE.reset(token)
