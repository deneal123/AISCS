"""Selective decode for an authenticated chunk without changing its producer.

The full descriptor, source identities and compressed bytes are verified before
selection.  This mirrors the bounded v1 reader; a caller must use the original
reader if that implementation changes.  The cache's producer hash is untouched.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.geometry_cache import chunk

# Bound this alternate reader to the reviewed implementation it mirrors.
REVIEWED_CHUNK_SHA256 = '702c9a12eec90d5dd755d191c911c55e2aa8412a5a471f1fe86c5eabfe1dfadd'


def supports_reader() -> bool:
    """Decline this optimization if the source reader cannot be verified."""
    try:
        source_digest = hashlib.sha256(Path(chunk.__file__).read_bytes()).hexdigest()
        return source_digest == REVIEWED_CHUNK_SHA256
    except OSError:
        return False


def read_selected_chunk(path: Path, descriptor: dict, *, audited_sources: dict, wanted: set[int]):
    """Read selected rows after checking every entry and all stored bytes."""
    if not isinstance(wanted, set | frozenset) or any(type(item) is not int or item <= 0
                                                       for item in wanted):
        raise ValueError('Invalid selected geometry IDs')
    if (not isinstance(descriptor, dict) or not isinstance(audited_sources, dict)
            or descriptor.get('format') != 'malecns-packed-geometry-chunk-v1'
            or type(descriptor.get('vertices')) is not int
            or not 1 <= descriptor['vertices'] <= chunk._MAX_VERTICES
            or type(descriptor.get('bytes')) is not int or descriptor['bytes'] <= 0
            or not isinstance(descriptor.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256'])
            or not isinstance(descriptor.get('neurons'), list) or not descriptor['neurons']):
        raise ValueError('Invalid packed geometry descriptor')
    raw_size = descriptor['vertices'] * chunk._RECORD.itemsize
    compression = descriptor.get('compression', 'none')
    if ((compression == 'none' and descriptor['bytes'] != raw_size)
            or (compression == 'zlib-1' and (descriptor.get('uncompressed_bytes') != raw_size
                                             or descriptor['bytes'] > raw_size + 65536))
            or compression not in ('none', 'zlib-1')):
        raise ValueError('Invalid packed geometry compression')
    offset, seen = 0, set()
    for item in descriptor['neurons']:
        if (not isinstance(item, dict) or type(item.get('offset')) is not int
                or item['offset'] != offset or type(item.get('count')) is not int
                or item['count'] <= 0):
            raise ValueError('Invalid packed geometry layout')
        body, source = item.get('body_id'), item.get('source_sha256')
        chunk._identity(body, source, audited_sources)
        if body in seen:
            raise ValueError('Duplicate packed geometry source')
        seen.add(body)
        offset += item['count']
    if offset != descriptor['vertices']:
        raise ValueError('Invalid packed geometry layout')
    with path.open('rb') as stream:
        raw = stream.read(descriptor['bytes'] + 1)
    if len(raw) != descriptor['bytes'] or hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('Packed geometry checksum mismatch')
    if compression == 'zlib-1':
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(raw, raw_size + 1)
        except zlib.error as exc:
            raise ValueError('Invalid compressed geometry') from exc
        if (len(decoded) != raw_size or not decoder.eof or decoder.unused_data
                or decoder.unconsumed_tail):
            raise ValueError('Invalid compressed geometry')
        raw = decoded
    rows = np.frombuffer(raw, dtype=chunk._RECORD)
    result = []
    for item in descriptor['neurons']:
        if int(item['body_id']) not in wanted:
            continue
        record = rows[item['offset']:item['offset'] + item['count']]
        points = np.column_stack((record['x'], record['y'], record['z']))
        geometry = (record['id'].astype(np.int64), points,
                    record['parent'].astype(np.int64), record['radius'])
        result.append({'skeleton': {'body_id': item['body_id'], 'sha256': item['source_sha256'],
                                    'source': f'{BASE}{item["body_id"]}.swc',
                                    'source_units': '8 nm'},
                       'geometry': geometry, 'points': points})
    return result
