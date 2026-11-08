"""Bounded read-ahead for independently authenticated geometry chunks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


def prefetch(chunks):
    """Read at most one subsequent chunk; propagate source failures to the caller."""
    iterator = iter(chunks)
    sentinel = object()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='geometry-read') as executor:
        future = executor.submit(next, iterator, sentinel)
        try:
            while True:
                chunk = future.result()
                if chunk is sentinel:
                    return
                future = executor.submit(next, iterator, sentinel)
                yield chunk
        finally:
            # Do not close an iterator while its worker is executing next().
            future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            close = getattr(iterator, 'close', None)
            if callable(close):
                close()
