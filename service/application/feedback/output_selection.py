"""Read or build the output-selection table for one preparation identity."""

import os

from service.infrastructure.stimulation.experimental_gpu.selection_cache import (
    HAS_CANDIDATES,
    HAS_PLACEHOLDERS,
    SelectionCache,
    preparation_identity,
    selection_identity,
)


def selection_cache_directory():
    """Return the configured selection directory, or None when it is unset."""
    from service.settings import output_selection_cache_directory

    return output_selection_cache_directory()


def _params_identity(params):
    from service.infrastructure.stimulation.experimental_gpu.narrow_cache import (
        params_identity,
    )

    return params_identity(params)


def open_output_selection(metadata, options, *, directory, threshold_mv, duration_ms,
                          max_source_distance_um):
    """Return a handle for this identity's selection, empty unless one is stored.

    The handle is opened against the identity the pass will use, so a table built
    under a different preparation, threshold or distance cut is never read: the
    digest names the question, and the table is only an answer to that question.
    """
    if not isinstance(directory, (str, os.PathLike)):
        raise ValueError('Invalid output selection directory')
    params = _params_identity(options['params'])
    identity = selection_identity(params_identity=params, threshold_mv=threshold_mv,
        duration_ms=duration_ms, max_distance_um=max_source_distance_um,
        preparation_sha256=preparation_identity(metadata, params))
    return OutputSelection(SelectionCache(directory, identity))


class OutputSelection:
    """One selection table and the counters a receipt is allowed to quote.

    The table is published only for a pass that finished and verified: an entry
    covering a pass that failed would let a later run skip the computation that
    produced its own evidence. A pass that cannot build a table runs as it always
    did, with the selection computed from the durable payload.
    """

    def __init__(self, cache):
        self.cache = cache
        self.identity = cache.identity
        self.hits = 0
        self.misses = 0
        self.loaded = cache.load()
        self._bodies = []
        self._offsets = [0]
        self._indices = []
        self._flags = []
        self._building = not self.loaded
        self._published = False
        self._incomplete = False
        self._expected = None

    def entry_for(self, body):
        """Return (indices, flags) for one cell, or None when it must be planned."""
        if not self.loaded:
            return None
        entry = self.cache.entry_for(body)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        return entry

    def expect(self, cells):
        """Declare how many cells a complete table must cover."""
        self._expected = int(cells)

    def note_incomplete(self):
        """Refuse to publish a table that does not cover the population it saw."""
        self._incomplete = True

    def record(self, body, indices, *, placeholders):
        """Remember one cell's answer so a finished pass can publish it."""
        if not self._building:
            return
        self._bodies.append(int(body))
        self._indices.extend(int(value) for value in indices)
        self._offsets.append(len(self._indices))
        self._flags.append((HAS_CANDIDATES if indices else 0)
                           | (HAS_PLACEHOLDERS if placeholders else 0))

    def commit(self):
        if self._incomplete or not self._building or self._published or not self._bodies:
            return None
        if self._expected is not None and len(self._bodies) != self._expected:
            # A pass that resumed, or that covered a slice, has seen only part of
            # the population: publishing that table would let a later full pass
            # record only the cells this one happened to reach.
            return None
        import numpy as np

        header = self.cache.store(np.asarray(self._bodies, dtype=np.int64),
            np.asarray(self._offsets, dtype=np.int64),
            np.asarray(self._indices, dtype=np.int32),
            np.asarray(self._flags, dtype=np.uint8))
        self._published = True
        self._building = False
        self.loaded = True
        return header

    def receipt(self):
        return {'identity': self.identity, 'loaded': bool(self.loaded),
                'cells': 0 if self.cache.bodies is None else int(len(self.cache.bodies)),
                'compartments': 0 if self.cache.indices is None
                else int(len(self.cache.indices)),
                'hits': self.hits, 'misses': self.misses,
                'built': bool(self._published), 'incomplete': bool(self._incomplete)}
