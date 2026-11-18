"""Read selected cells from a completely identified packed morphology snapshot.

Authenticating the snapshot (audit of the independent source index plus the
22 MB manifest) is a fixed cost of roughly 2.5 s.  `SelectedCache` pays it once
and then serves bounded reads, so a population-wide run does not re-audit the
snapshot for every target cell.
"""

from __future__ import annotations

import hashlib
import json
import re

from service.infrastructure.stimulation.geometry_cache import cache, index, selected_chunk
from service.infrastructure.stimulation.geometry_cache.producer_compatibility import (
    producer_is_compatible,
)
from service.infrastructure.stimulation.geometry_cache.selected_parallel import iter_decoded_chunks


class SelectedCache:
    """One authenticated snapshot, reusable for many bounded selections.

    Construction verifies the independent source audit, the manifest digest and
    the complete chunk ordering.  Each read still verifies the bytes of every
    chunk it touches; unused chunks are never read.
    """

    def __init__(self, directory, *, expected_manifest_sha256, graph_ids, graph_sha256,
                 source_index, source_audit, workers=1):
        if type(workers) is not int or not 1 <= workers <= 8:
            raise ValueError('Invalid selected geometry workers')
        if (not isinstance(expected_manifest_sha256, str)
                or not re.fullmatch(r'[a-f0-9]{64}', expected_manifest_sha256)):
            raise ValueError('Invalid geometry cache manifest identity')
        raw_ids = list(graph_ids)
        ids = [int(value) for value in raw_ids]
        sources, source_sha = index.audited_geometry_sources(source_index, source_audit,
                                                             raw_ids, graph_sha256)
        try:
            raw = (directory / 'manifest.json').read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
                raise ValueError('Geometry cache manifest checksum mismatch')
            metadata = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Geometry cache manifest unavailable') from exc
        if (not isinstance(metadata, dict)
                or metadata.get('format') != 'malecns-packed-geometry-cache-v1'
                or metadata.get('graph_sha256') != graph_sha256
                or metadata.get('source_index_sha256') != source_sha
                or not producer_is_compatible(
                    expected_manifest_sha256, metadata.get('producer_sha256'),
                    cache._producer_sha256())
                or type(metadata.get('neurons')) is not int or metadata['neurons'] != len(ids)
                or type(metadata.get('vertices')) is not int or metadata['vertices'] < 1
                or not isinstance(metadata.get('chunks'), list) or not metadata['chunks']):
            raise ValueError('Geometry cache manifest does not match source snapshot')
        ordered, vertices, descriptors, bodies = [], 0, [], []
        for position, descriptor in enumerate(metadata['chunks']):
            if (not isinstance(descriptor, dict)
                    or descriptor.get('name') != f'chunk-{position:06d}.bin'
                    or not isinstance(descriptor.get('neurons'), list)
                    or type(descriptor.get('vertices')) is not int):
                raise ValueError('Invalid geometry cache chunk list')
            try:
                chunk_ids = [int(item['body_id']) for item in descriptor['neurons']]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('Invalid geometry cache source list') from exc
            ordered.extend(chunk_ids)
            vertices += descriptor['vertices']
            descriptors.append(descriptor)
            bodies.append(chunk_ids)
        if ordered != ids or vertices != metadata['vertices']:
            raise ValueError('Geometry cache is incomplete or out of order')
        self._directory = directory
        self._sources = sources
        self._ids = ids
        self._descriptors = descriptors
        self._bodies = bodies
        self._chunk_of = {body: position for position, chunk_ids
                          in enumerate(bodies) for body in chunk_ids}
        self._workers = workers
        self.manifest_sha256 = expected_manifest_sha256
        self.source_index_sha256 = source_sha

    @property
    def graph_ids(self):
        return list(self._ids)

    def chunk_bodies(self, body):
        """Registered bodies packed into the same verified chunk, in chunk order."""
        position = self._chunk_of.get(int(body)) if type(body) is int else None
        return [] if position is None else list(self._bodies[position])

    def chunk_index(self, body):
        """Chunk ordinal for `body` in the verified snapshot, or None."""
        return self._chunk_of.get(int(body)) if type(body) is int else None

    def entries(self, selected_ids, *, workers=None):
        """Yield the chosen entries after verifying their chunks; unused chunks stay unread."""
        selection = list(selected_ids)
        if (any(type(value) is not int or value <= 0 for value in selection)
                or len(set(selection)) != len(selection) or not set(selection).issubset(self._ids)):
            raise ValueError('Invalid selected geometry IDs')
        wanted = set(selection)
        if not wanted:
            return
        positions = sorted({self._chunk_of[body] for body in wanted})
        found = 0
        for entries in iter_decoded_chunks(self._directory, [self._descriptors[p] for p in positions],
                                           sources=self._sources, wanted=wanted,
                                           selective=selected_chunk.supports_reader(),
                                           workers=self._workers if workers is None else workers):
            for entry in entries:
                if int(entry['skeleton']['body_id']) in wanted:
                    found += 1
                    yield entry
        if found != len(wanted):
            raise ValueError('Selected geometry missing from cache')


def iter_selected_cache(directory, *, expected_manifest_sha256, graph_ids, graph_sha256,
                        source_index, source_audit, selected_ids, workers=1):
    """Authenticate the snapshot and every used chunk; leave unused chunks unread.

    Selection must come from a separately verified conservative spatial filter.
    This verifies snapshot identity, not whether its source SWCs have since changed.
    """
    snapshot = SelectedCache(directory, expected_manifest_sha256=expected_manifest_sha256,
        graph_ids=graph_ids, graph_sha256=graph_sha256, source_index=source_index,
        source_audit=source_audit, workers=workers)
    return snapshot.entries(selected_ids)
