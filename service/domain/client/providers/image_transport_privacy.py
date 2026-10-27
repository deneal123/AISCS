"""Suppress payload-bearing SDK diagnostics only inside private image operations."""

from contextlib import contextmanager
from contextvars import ContextVar
from logging import Filter, LogRecord, getLogger

_PRIVATE_IMAGE_TRANSPORT: ContextVar[bool] = ContextVar("private_image_transport", default=False)


class _PrivateImageFilter(Filter):
    def filter(self, record: LogRecord) -> bool:
        # Do not inspect, stringify or redact provider payloads. During this
        # operation only our own closed diagnostics are permitted to be emitted.
        return not _PRIVATE_IMAGE_TRANSPORT.get()


_FILTER = _PrivateImageFilter()
for _name in (
    "openai._base_client",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "PIL.Image",
    "PIL.ImageFile",
    "PIL.PngImagePlugin",
    "PIL.JpegImagePlugin",
    "PIL.TiffImagePlugin",
    "PIL.BmpImagePlugin",
):
    getLogger(_name).addFilter(_FILTER)


@contextmanager
def private_image_transport(*, enabled: bool = True):
    """Context-local scope; unrelated concurrent request logging is unchanged."""
    if not enabled:
        yield
        return
    token = _PRIVATE_IMAGE_TRANSPORT.set(True)
    try:
        yield
    finally:
        _PRIVATE_IMAGE_TRANSPORT.reset(token)


async def private_stream_chunks(stream, *, enabled: bool):
    """Never hold a ContextVar token across an async-generator yield."""
    iterator = aiter(stream)
    while True:
        with private_image_transport(enabled=enabled):
            try:
                chunk = await anext(iterator)
            except StopAsyncIteration:
                return
        yield chunk
