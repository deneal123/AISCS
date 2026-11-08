"""Bounded, lossless geometry chunks for an independently audited SWC snapshot.

The writer must receive geometries produced by the checked SWC reader. Chunk
hashes and source hashes are integrity checks, not self-authenticating proof:
the caller must obtain the expected manifest and source hashes independently.
This format is not yet connected to field execution.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.morphology_repository import BASE

_RECORD = np.dtype([('x', '<f8'), ('y', '<f8'), ('z', '<f8'), ('radius', '<f8'),
                    ('parent', '<i4'), ('id', '<i4')])
_MAX_VERTICES = 1_000_000  # The existing GPU batch limit, not a neuron selection limit.


def _identity(body, source_sha, audited_sources):
    if (not isinstance(body, str) or not re.fullmatch(r'[1-9][0-9]*', body)
            or int(body) >= 2**63 or not isinstance(source_sha, str)
            or not re.fullmatch(r'[0-9a-f]{64}', source_sha)
            or audited_sources.get(int(body)) != source_sha):
        raise ValueError('Packed geometry source identity mismatch')


def _checked_entry(entry, audited_sources):
    try:
        skeleton, geometry = entry['skeleton'], entry['geometry']
        body, source = skeleton['body_id'], skeleton['sha256']
        ids, points, parents, radii = (np.asarray(value) for value in geometry)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid packed geometry entry') from exc
    _identity(body, source, audited_sources)
    if skeleton.get('source') != f'{BASE}{body}.swc' or skeleton.get('source_units') != '8 nm':
        raise ValueError('Packed geometry source locator mismatch')
    if ids.ndim != 1:
        raise ValueError('Invalid packed geometry arrays')
    n = len(ids)
    if (not 1 <= n <= _MAX_VERTICES or ids.dtype.kind not in 'iu'
            or points.shape != (n, 3) or points.dtype.kind != 'f'
            or parents.shape != (n,) or parents.dtype.kind != 'i'
            or radii.shape != (n,) or radii.dtype.kind != 'f'
            or np.any(ids <= 0) or np.any(ids >= 2**31) or len(np.unique(ids)) != n
            or np.any(parents < -1) or np.any(parents >= n)
            or not np.isfinite(points).all() or not np.isfinite(radii).all()
            or np.any(radii < 0)):
        raise ValueError('Invalid packed geometry arrays')
    # Requiring float64 avoids silently changing the checked SWC representation.
    if points.dtype != np.float64 or radii.dtype != np.float64:
        raise ValueError('Packed geometry requires float64 coordinates and radii')
    return body, source, ids, points, parents, radii


def write_chunk(path: Path, entries, *, audited_sources: dict, compression='none'):
    """Write verified-prepared entries in order, never replacing an existing file.

    `audited_sources` must come from the independently verified source index.
    The returned descriptor must be bound to a trusted graph and manifest by
    the caller before future reuse.
    """
    if (compression not in ('none', 'zlib-1')
            or not isinstance(audited_sources, dict) or not isinstance(entries, (list, tuple))
            or not entries):
        raise ValueError('Invalid packed geometry chunk input')
    checked, seen, total = [], set(), 0
    for entry in entries:
        item = _checked_entry(entry, audited_sources)
        body = item[0]
        if body in seen:
            raise ValueError('Duplicate packed geometry source')
        seen.add(body)
        total += len(item[2])
        if total > _MAX_VERTICES:
            raise ValueError('Packed geometry chunk exceeds vertex limit')
        checked.append(item)
    metadata, digest, offset, stored = [], hashlib.sha256(), 0, 0
    compressor = zlib.compressobj(level=1) if compression == 'zlib-1' else None
    stream = path.open('xb')
    try:
        with stream:
            for body, source, ids, points, parents, radii in checked:
                rows = np.empty(len(ids), dtype=_RECORD)
                for axis, name in enumerate(('x', 'y', 'z')):
                    rows[name] = points[:, axis]
                rows['radius'], rows['parent'], rows['id'] = radii, parents, ids
                view = memoryview(rows).cast('B')
                payload = compressor.compress(view) if compressor is not None else view
                if stream.write(payload) != len(payload):
                    raise OSError('Incomplete packed geometry write')
                digest.update(payload)
                stored += len(payload)
                metadata.append({'body_id': body, 'source_sha256': source,
                                 'offset': offset, 'count': len(ids)})
                offset += len(ids)
            if compressor is not None:
                payload = compressor.flush()
                if stream.write(payload) != len(payload):
                    raise OSError('Incomplete packed geometry write')
                digest.update(payload)
                stored += len(payload)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    descriptor = {'format': 'malecns-packed-geometry-chunk-v1', 'vertices': total,
                  'bytes': stored, 'sha256': digest.hexdigest(), 'neurons': metadata}
    if compressor is not None:
        descriptor.update({'compression': compression,
                           'uncompressed_bytes': total * _RECORD.itemsize})
    return descriptor


def read_chunk(path: Path, descriptor: dict, *, audited_sources: dict):
    """Read the exact hashed bytes of a chunk described by a trusted manifest."""
    if (not isinstance(descriptor, dict) or not isinstance(audited_sources, dict)
            or descriptor.get('format') != 'malecns-packed-geometry-chunk-v1'
            or type(descriptor.get('vertices')) is not int
            or not 1 <= descriptor['vertices'] <= _MAX_VERTICES
            or type(descriptor.get('bytes')) is not int or descriptor['bytes'] <= 0
            or not isinstance(descriptor.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256'])
            or not isinstance(descriptor.get('neurons'), list) or not descriptor['neurons']):
        raise ValueError('Invalid packed geometry descriptor')
    raw_size = descriptor['vertices'] * _RECORD.itemsize
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
        _identity(body, source, audited_sources)
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
    rows = np.frombuffer(raw, dtype=_RECORD)
    result = []
    for item in descriptor['neurons']:
        record = rows[item['offset']:item['offset'] + item['count']]
        points = np.column_stack((record['x'], record['y'], record['z']))
        geometry = (record['id'].astype(np.int64), points,
                    record['parent'].astype(np.int64), record['radius'])
        result.append({'skeleton': {'body_id': item['body_id'], 'sha256': item['source_sha256'],
                                    'source': f'{BASE}{item["body_id"]}.swc',
                                    'source_units': '8 nm'},
                       'geometry': geometry, 'points': points})
    return result
