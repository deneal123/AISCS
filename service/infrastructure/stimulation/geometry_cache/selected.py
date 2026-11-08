"""Read selected cells from a completely identified packed morphology snapshot."""

from __future__ import annotations

import hashlib
import json
import re

from service.infrastructure.stimulation.geometry_cache import cache, chunk, index


def iter_selected_cache(directory, *, expected_manifest_sha256, graph_ids, graph_sha256,
                        source_index, source_audit, selected_ids):
    """Authenticate the snapshot and every used chunk; leave unused chunks unread.

    Selection must come from a separately verified conservative spatial filter.
    This verifies snapshot identity, not whether its source SWCs have since changed.
    """
    if (not isinstance(expected_manifest_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', expected_manifest_sha256)):
        raise ValueError('Invalid geometry cache manifest identity')
    raw_ids = list(graph_ids)
    ids = [int(value) for value in raw_ids]
    selection = list(selected_ids)
    if (any(type(value) is not int or value <= 0 for value in selection)
            or len(set(selection)) != len(selection) or not set(selection).issubset(ids)):
        raise ValueError('Invalid selected geometry IDs')
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
            or metadata.get('producer_sha256') != cache._producer_sha256()
            or type(metadata.get('neurons')) is not int or metadata['neurons'] != len(ids)
            or type(metadata.get('vertices')) is not int or metadata['vertices'] < 1
            or not isinstance(metadata.get('chunks'), list) or not metadata['chunks']):
        raise ValueError('Geometry cache manifest does not match source snapshot')
    ordered, vertices, wanted = [], 0, set(selection)
    relevant = []
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
        if wanted.intersection(chunk_ids):
            relevant.append(descriptor)
    if ordered != ids or vertices != metadata['vertices']:
        raise ValueError('Geometry cache is incomplete or out of order')
    found = 0
    for descriptor in relevant:
        entries = chunk.read_chunk(directory / descriptor['name'], descriptor,
                                   audited_sources=sources)
        for entry in entries:
            if int(entry['skeleton']['body_id']) in wanted:
                found += 1
                yield entry
    if found != len(wanted):
        raise ValueError('Selected geometry missing from cache')
