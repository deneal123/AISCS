"""Exact sparse per-tick LIF differences, bound to a graph and configuration."""

from __future__ import annotations

import re
import struct

import numpy as np

from service.domain.target_response_limits import MAX_TARGET_RESPONSE_VALUES

HEADER = struct.Struct('<4sIII32s32s')


def encode_sparse_delta(sparse, *, graph, source_ids, duration_ms, configuration_sha256):
    graph_hash = graph.provenance.get('manifest_sha256')
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
           for value in (graph_hash, configuration_sha256)):
        raise ValueError('Invalid sparse identity')
    if not isinstance(sparse, dict) or sparse.get('status') != 'recorded':
        raise ValueError('Invalid sparse result')
    offsets = np.asarray(sparse.get('offsets'))
    indices = np.asarray(sparse.get('indices'))
    values = np.asarray(sparse.get('values'))
    source_positions = np.searchsorted(graph.ids, source_ids)
    if (type(duration_ms) is not int or not 1 <= duration_ms <= 1000
            or graph.size < 1 or graph.size >= 2**31
            or offsets.shape != (duration_ms + 2,) or offsets.dtype.kind not in 'iu'
            or indices.ndim != 1 or indices.dtype.kind not in 'iu'
            or values.dtype != np.float32 or values.shape != indices.shape
            or len(values) > MAX_TARGET_RESPONSE_VALUES
            or offsets[0] != 0 or offsets[1] != 0 or offsets[-1] != len(values)
            or np.any(offsets[1:] < offsets[:-1])
            or np.any(indices < 0) or np.any(indices >= graph.size)
            or not np.isfinite(values).all() or np.any(values == 0)
            or np.isin(indices, source_positions).any()):
        raise ValueError('Invalid sparse data')
    for start, end in zip(offsets[:-1], offsets[1:], strict=True):
        selected = indices[int(start):int(end)]
        if np.any(selected[1:] <= selected[:-1]):
            raise ValueError('Invalid sparse order')
    header = HEADER.pack(b'SPD1', graph.size, duration_ms + 1, len(values),
                         bytes.fromhex(graph_hash), bytes.fromhex(configuration_sha256))
    return (header + np.asarray(offsets, dtype='<u4').tobytes()
            + np.asarray(indices, dtype='<u4').tobytes()
            + np.asarray(values, dtype='<f4').tobytes())


def decode_sparse_delta(data, *, graph, source_ids, duration_ms, configuration_sha256):
    if not isinstance(data, bytes) or len(data) < HEADER.size:
        raise ValueError('Invalid sparse artifact')
    magic, nodes, samples, count, graph_hash, config_hash = HEADER.unpack_from(data)
    if (magic != b'SPD1' or nodes != graph.size or samples != duration_ms + 1
            or count > MAX_TARGET_RESPONSE_VALUES
            or len(data) != HEADER.size + 4 * (samples + 1) + 8 * count
            or graph_hash.hex() != graph.provenance.get('manifest_sha256')
            or config_hash.hex() != configuration_sha256):
        raise ValueError('Invalid sparse header')
    offsets = np.frombuffer(data, dtype='<u4', count=samples + 1, offset=HEADER.size)
    index_offset = HEADER.size + 4 * (samples + 1)
    indices = np.frombuffer(data, dtype='<u4', count=count, offset=index_offset)
    values = np.frombuffer(data, dtype='<f4', count=count, offset=index_offset + 4 * count)
    sparse = {'status': 'recorded', 'offsets': offsets, 'indices': indices, 'values': values}
    if encode_sparse_delta(sparse, graph=graph, source_ids=source_ids, duration_ms=duration_ms,
                           configuration_sha256=configuration_sha256) != data:
        raise ValueError('Sparse artifact mismatch')
    return sparse


def validate_sparse_snapshots(sparse, response, graph):
    """Check every saved dense snapshot against the exact sparse tick, including zeros."""
    positions = np.searchsorted(graph.ids, response['target_ids'])
    if (np.any(positions >= graph.size)
            or not np.array_equal(graph.ids[positions], response['target_ids'])):
        raise ValueError('Sparse snapshot graph mismatch')
    offsets, indices, values = (sparse[key] for key in ('offsets', 'indices', 'values'))
    for row, tick in enumerate(response['time_ms'].astype(int)):
        dense = np.zeros(graph.size, dtype=np.float32)
        start, end = offsets[tick:tick + 2]
        dense[indices[int(start):int(end)]] = values[int(start):int(end)]
        expected = response['active_relative_mv'][row] - response['control_relative_mv'][row]
        if not np.array_equal(dense[positions], expected):
            raise ValueError('Sparse snapshot difference mismatch')
