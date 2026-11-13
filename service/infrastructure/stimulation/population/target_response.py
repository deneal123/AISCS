"""Bounded paired LIF target traces; independent of physiological validity."""

from __future__ import annotations

import io
import re
import struct
import zipfile

import numpy as np

from service.domain.target_response_limits import can_capture_targets, network_sample_ticks

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
ARRAY_NAMES = ('target_ids', 'time_ms', 'active_relative_mv', 'control_relative_mv')


def expected_direct_targets(schedules, source_ids):
    """Return all unique event targets except silenced source cells."""
    return sorted({event['target_id'] for schedule in schedules
                   for event in schedule['edge_events']} - set(source_ids))


def validate_response_arrays(arrays, *, schedules, source_ids, duration_ms, network_ids=None):
    """Validate identity, shape and finiteness, not the correctness of LIF parameters."""
    if (not isinstance(arrays, dict) or set(arrays) != set(ARRAY_NAMES)
            or type(duration_ms) is not int or not 1 <= duration_ms <= 1000):
        raise ValueError('Invalid target response')
    excluded = set(source_ids)
    expected = (expected_direct_targets(schedules, source_ids) if network_ids is None
                else [int(body) for body in network_ids if int(body) not in excluded])
    ticks = (list(range(duration_ms + 1)) if network_ids is None
             else network_sample_ticks(len(expected), duration_ms))
    if ticks is None or not can_capture_targets(len(expected), len(ticks) - 1):
        raise ValueError('Invalid target response coverage')
    ids, time, active, control = (np.asarray(arrays[name]) for name in ARRAY_NAMES)
    shape = (len(ticks), len(expected))
    if (ids.ndim != 1 or ids.dtype.kind not in 'iu' or not np.array_equal(ids, expected)
            or time.shape != (len(ticks),) or time.dtype.kind != 'f'
            or not np.array_equal(time, np.asarray(ticks, dtype=np.float32))
            or active.shape != shape or control.shape != shape
            or active.dtype != np.float32 or control.dtype != np.float32
            or not np.isfinite(active).all() or not np.isfinite(control).all()
            or not np.array_equal(active[0], control[0])):
        raise ValueError('Invalid target response arrays')
    return {'target_ids': ids, 'time_ms': time, 'active_relative_mv': active,
            'control_relative_mv': control}


def encode_target_response(arrays, *, schedules, source_ids, duration_ms, network_ids=None):
    verified = validate_response_arrays(arrays, schedules=schedules, source_ids=source_ids,
                                        duration_ms=duration_ms, network_ids=network_ids)
    out = io.BytesIO()
    np.savez_compressed(out, **verified)
    data = out.getvalue()
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError('Target response exceeds artifact limit')
    return data


def encode_target_response_binary(arrays, *, schedules, source_ids, duration_ms,
                                  graph_sha256, configuration_sha256, network_ids=None):
    verified = validate_response_arrays(arrays, schedules=schedules, source_ids=source_ids,
                                        duration_ms=duration_ms, network_ids=network_ids)
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
           for value in (graph_sha256, configuration_sha256)):
        raise ValueError('Invalid target response identity')
    ids = np.asarray(verified['target_ids'], dtype='<u8')
    delta = verified['active_relative_mv'] - verified['control_relative_mv']
    if not np.isfinite(delta).all():
        raise ValueError('Invalid target response difference')
    times = verified['time_ms']
    decimated = network_ids is not None and len(times) != duration_ms + 1
    magic = b'FRS1' if network_ids is None else b'FRS3' if decimated else b'FRS2'
    header = struct.pack('<4sII32s32s', magic, len(ids), len(times),
                         bytes.fromhex(graph_sha256), bytes.fromhex(configuration_sha256))
    times_binary = np.asarray(times, dtype='<u4').tobytes() if decimated else b''
    return header + times_binary + ids.tobytes() + np.asarray(delta, dtype='<f4').tobytes()


def decode_target_response(data, *, schedules, source_ids, duration_ms, network_ids=None):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_RESPONSE_BYTES:
        raise ValueError('Invalid target response artifact')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if (len(members) != len(ARRAY_NAMES)
                or {entry.filename for entry in members} != {name + '.npy' for name in ARRAY_NAMES}
                or sum(entry.file_size for entry in members) > MAX_RESPONSE_BYTES):
            raise ValueError('Invalid target response archive')
        count = (len(expected_direct_targets(schedules, source_ids)) if network_ids is None
                 else len(network_ids) - len(source_ids))
        ticks = (list(range(duration_ms + 1)) if network_ids is None
                 else network_sample_ticks(count, duration_ms))
        if ticks is None or not can_capture_targets(count, len(ticks) - 1) or duration_ms > 1000:
            raise ValueError('Invalid target response coverage')
        shapes = {'target_ids': (count,), 'time_ms': (len(ticks),),
                  'active_relative_mv': (len(ticks), count),
                  'control_relative_mv': (len(ticks), count)}
        for member in members:
            name = member.filename[:-4]
            with archive.open(member) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError('Unsupported target response array format')
            if (shape != shapes[name] or fortran or dtype.hasobject
                    or (name == 'target_ids'
                        and dtype not in (np.dtype('int64'), np.dtype('uint64')))
                    or (name != 'target_ids' and dtype != np.dtype('float32'))):
                raise ValueError('Invalid target response array header')
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in ARRAY_NAMES}
    return validate_response_arrays(arrays, schedules=schedules, source_ids=source_ids,
                                    duration_ms=duration_ms, network_ids=network_ids)
