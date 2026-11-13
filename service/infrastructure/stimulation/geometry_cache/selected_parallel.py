"""Bounded, ordered decoding of independently authenticated chunks."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor

from service.infrastructure.stimulation.geometry_cache import chunk, selected_chunk


def iter_decoded_chunks(directory, descriptors, *, sources, wanted, selective, workers):
    """Decode at most `workers` chunks concurrently without reordering them.

    Each chunk is fully verified by its reader. Closing the iterator cancels
    pending work and joins the owned worker threads before returning.
    """
    if (type(workers) is not int or not 1 <= workers <= 8 or type(selective) is not bool):
        raise ValueError('Invalid chunk decoding concurrency')

    def read(descriptor):
        path = directory / descriptor['name']
        if selective:
            return selected_chunk.read_selected_chunk(path, descriptor, audited_sources=sources,
                                                       wanted=wanted)
        return chunk.read_chunk(path, descriptor, audited_sources=sources)

    if workers == 1:
        for descriptor in descriptors:
            yield read(descriptor)
        return

    iterator = iter(descriptors)
    pending = deque()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='geometry-chunk') as executor:
        try:
            for _ in range(workers):
                try:
                    pending.append(executor.submit(read, next(iterator)))
                except StopIteration:
                    break
            while pending:
                entries = pending.popleft().result()
                try:
                    pending.append(executor.submit(read, next(iterator)))
                except StopIteration:
                    pass
                yield entries
        finally:
            for future in pending:
                future.cancel()
