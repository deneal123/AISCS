"""Decide whether a population pass can replay narrowed cells instead of
decoding and reducing them again.

Decoding a morphology chunk and reducing its tree are functions of the geometry
and the field configuration alone. Nothing about the stimulus, the schedule or
the recording changes them. A full-population experiment replays the same
166 700 cells four times, so repeating that work is pure cost: it measured
530 s of decoding plus 603 s of reduction in one 1141 s pass.

The cache is only ever a shorter route to the same cells. Its key covers the
geometry manifest, the source index, every preparation parameter and the three
options that change the narrowed record; its entries are only usable when the
chunk and body inventory matches the request exactly, so a pass over a slice,
with rejected cells or with a different visiting order simply misses. A miss
recomputes and republishes; a hit is verified record by record as it is read.
"""

from service.infrastructure.stimulation.experimental_gpu.narrow_cache import (
    NarrowCellCache,
    cache_key,
    geometry_digest,
    inventory,
    params_identity,
)
from service.infrastructure.stimulation.experimental_gpu.population_replay import (
    width_order,
)

__all__ = ['NarrowedCells', 'open_narrowed_cells']


class NarrowedCells:
    """One pass's use of the cache: a verified store, or a writer to fill."""

    __slots__ = ('_store', '_writer', '_key', '_meta', '_chunks', '_bodies')

    def __init__(self, store, writer, key, meta, chunks, bodies):
        self._store = store
        self._writer = writer
        self._key = key
        self._meta = meta
        self._chunks = chunks
        self._bodies = bodies

    @property
    def store(self):
        return self._store

    @property
    def writer(self):
        return self._writer

    @property
    def key(self):
        return self._key

    @property
    def reused(self):
        return self._store is not None

    def receipt(self):
        """What the pass used, for the run receipt. Never claims a hit it did not get."""
        if self._store is not None:
            return {'mode': 'restored', 'key': self._key, 'cells': self._store.cells,
                    'chunks': self._store.groups, 'payload_bytes': self._store.payload_bytes}
        if self._writer is not None and getattr(self._writer, 'committed', False):
            return {'mode': 'built', 'key': self._key, 'cells': self._meta['cells'],
                    'chunks': self._meta['chunks'],
                    'payload_bytes': self._meta['payload_bytes']}
        return {'mode': 'uncached', 'key': self._key}

    def commit(self):
        """Publish a built entry once the pass has actually finished."""
        if self._writer is None or getattr(self._writer, 'committed', False):
            return None
        # The published metadata is what a receipt may quote: until the entry is
        # committed its cell and byte counts do not exist yet, and reading them
        # from the open writer is how a receipt raised on a finished build.
        self._meta = self._writer.commit()
        return self._meta

    def abort(self):
        """Drop a partial entry: a half-written cache must never be reusable."""
        if self._writer is not None and not getattr(self._writer, 'committed', False):
            self._writer.discard()
            self._writer = None

    def close(self):
        if self._store is not None:
            self._store.close()


def open_narrowed_cells(metadata, params, *, directory, recording, events, reroot,
                        limit=None, order=None, source_index_sha256=None):
    """Open a matching entry, or start writing one; never raises on a cache miss."""
    if directory is None:
        return NarrowedCells(None, None, None, None, 0, None)
    if source_index_sha256 is None:
        # The geometry manifest already authenticates the morphology index it was
        # built from, so the pass does not have to thread the digest separately.
        source_index_sha256 = metadata.get('source_index_sha256')
    positions = width_order(metadata) if order is None else order
    chunks, bodies = inventory(metadata, positions, limit)
    key = cache_key(geometry_sha256=geometry_digest(metadata),
                    source_index_sha256=source_index_sha256,
                    params=params, recording=recording, events=events, reroot=reroot)
    cache = NarrowCellCache(directory)
    store = cache.open(key, chunks=chunks, bodies=bodies)
    if store is not None:
        return NarrowedCells(store, None, key, None, chunks, bodies)
    meta = {'geometry_sha256': geometry_digest(metadata),
            'source_index_sha256': source_index_sha256,
            # Stored as the flattened identity, not the object: the metadata
            # file is JSON and must round-trip what the key hashed.
            'params': params_identity(params),
            'recording': bool(recording), 'events': bool(events), 'reroot': bool(reroot)}
    try:
        writer = cache.writer(key, meta)
    except OSError:
        # A cache that cannot be written is a disabled cache, not a failed run.
        return NarrowedCells(None, None, key, None, chunks, bodies)
    return NarrowedCells(None, writer, key, None, chunks, bodies)