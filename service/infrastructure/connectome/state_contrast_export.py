"""Binary transport for sampled relative LIF state differences."""

from __future__ import annotations

import hashlib
import re

import numpy as np

_HASH = re.compile(r'^[0-9a-f]{64}$')
_MAX_VALUES = 4_000_000


def encode_state_contrast(result):
    """Return bytes and description; callers must authenticate the description."""
    provenance = result['provenance']
    ids = result['sampled_cell_ids']
    time = np.asarray(result['sampled_time_ms'])
    active = np.asarray(result['active_voltage_relative_mv'])
    control = np.asarray(result['control_voltage_relative_mv'])
    delta = np.asarray(result['voltage_difference_mv'])
    if (not isinstance(ids, list) or not ids or any(type(x) is not int or x <= 0 for x in ids)
            or len(ids) != len(set(ids)) or time.ndim != 1 or len(time) < 2
            or len(time) > 1001 or len(time) * len(ids) > _MAX_VALUES
            or not np.array_equal(time, np.arange(len(time)))
            or any(array.shape != (len(time), len(ids)) or not np.isfinite(array).all()
                   for array in (active, control, delta))
            or any(array.dtype != np.float32 for array in (active, control, delta))
            or not np.array_equal(delta, active - control)
            or any(not isinstance(provenance.get(key), str) or not _HASH.fullmatch(provenance[key])
                   for key in ('field_manifest_sha256', 'graph_sha256', 'graph_manifest_sha256'))):
        raise ValueError('Invalid state contrast')
    ids_bytes = np.asarray(ids, dtype='<u8').tobytes()
    delta_bytes = np.asarray(delta, dtype='<f4').tobytes(order='C')
    binary = ids_bytes + delta_bytes
    description = {
        'format': 'lif-state-contrast-v1',
        'field_manifest_sha256': provenance['field_manifest_sha256'],
        'graph_sha256': provenance['graph_sha256'],
        'graph_manifest_sha256': provenance['graph_manifest_sha256'],
        'cells': len(ids), 'samples': len(time), 'step_ms': 1,
        'byte_order': 'little', 'ids_dtype': '<u8', 'difference_dtype': '<f4',
        'difference_shape': [len(time), len(ids)],
        'difference_offset': len(ids_bytes), 'bytes': len(binary),
        'sha256': hashlib.sha256(binary).hexdigest(),
        'interpretation': 'relative LIF state difference against seeded no-input control; '
                          'not a measured potential or a spike',
    }
    return binary, description


def decode_state_contrast(binary, description, *, expected_field_manifest_sha256,
                          expected_graph_manifest_sha256, expected_graph_sha256, graph_ids):
    """Reject damaged or mismatched data before exposing numeric arrays."""
    if not isinstance(binary, bytes) or not isinstance(description, dict):
        raise ValueError('Invalid state contrast transport')
    cells, samples = description.get('cells'), description.get('samples')
    if (any(not isinstance(value, str) or not _HASH.fullmatch(value) for value in
            (expected_field_manifest_sha256, expected_graph_manifest_sha256, expected_graph_sha256))
            or description.get('format') != 'lif-state-contrast-v1'
            or description.get('field_manifest_sha256') != expected_field_manifest_sha256
            or description.get('graph_manifest_sha256') != expected_graph_manifest_sha256
            or description.get('graph_sha256') != expected_graph_sha256
            or type(cells) is not int or cells < 1 or type(samples) is not int
            or not 2 <= samples <= 1001
            or cells * samples > _MAX_VALUES or type(description.get('step_ms')) is not int
            or description['step_ms'] != 1
            or description.get('byte_order') != 'little' or description.get('ids_dtype') != '<u8'
            or description.get('difference_dtype') != '<f4'
            or description.get('difference_shape') != [samples, cells]
            or description.get('difference_offset') != 8 * cells
            or description.get('bytes') != len(binary)
            or len(binary) != 8 * cells + 4 * cells * samples
            or description.get('sha256') != hashlib.sha256(binary).hexdigest()):
        raise ValueError('Invalid or mismatched state contrast description')
    ids = np.frombuffer(binary, dtype='<u8', count=cells)
    values = np.frombuffer(binary, dtype='<f4', count=cells * samples, offset=8 * cells)
    graph_ids = np.asarray(graph_ids)
    if graph_ids.ndim != 1 or np.any(graph_ids[1:] <= graph_ids[:-1]):
        raise ValueError('Invalid registered graph IDs')
    positions = np.searchsorted(graph_ids, ids)
    if (len(np.unique(ids)) != cells or np.any(ids == 0) or np.any(positions >= len(graph_ids))
            or not np.array_equal(graph_ids[positions], ids) or not np.isfinite(values).all()):
        raise ValueError('Invalid state contrast cells or values')
    return {'cell_ids': ids, 'time_ms': np.arange(samples, dtype=np.float32),
            'voltage_difference_mv': values.reshape(samples, cells)}
