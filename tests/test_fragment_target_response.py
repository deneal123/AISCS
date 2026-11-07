import io
import struct

import numpy as np
import pytest

from service.domain.target_response_limits import can_capture_targets
from service.infrastructure.stimulation.fragment_target_response import (
    decode_target_response,
    encode_target_response,
    encode_target_response_binary,
)


def fixture():
    schedules = [{'edge_events': [{'target_id': 20}, {'target_id': 30}, {'target_id': 20}]}]
    active = np.zeros((4, 2), dtype=np.float32)
    active[2:, 0] = -.25
    arrays = {'target_ids': np.array([20, 30], dtype=np.int64),
              'time_ms': np.arange(4, dtype=np.float32), 'active_relative_mv': active,
              'control_relative_mv': np.zeros((4, 2), dtype=np.float32)}
    return schedules, arrays


def test_response_roundtrips_and_is_bound_to_target_selection():
    schedules, arrays = fixture()
    kwargs = {'schedules': schedules, 'source_ids': [10], 'duration_ms': 3}
    data = encode_target_response(arrays, **kwargs)
    checked = decode_target_response(data, **kwargs)
    np.testing.assert_array_equal(checked['active_relative_mv'], arrays['active_relative_mv'])
    with pytest.raises(ValueError, match='arrays'):
        decode_target_response(data, **{**kwargs, 'schedules': [
            {'edge_events': [{'target_id': 20}, {'target_id': 40}]}]})


@pytest.mark.parametrize('key,value', [
    ('target_ids', np.array([30, 20], dtype=np.int64)),
    ('time_ms', np.array([0., 1., 2., 4.], dtype=np.float32)),
    ('active_relative_mv', np.full((4, 2), np.nan, dtype=np.float32)),
    ('control_relative_mv', np.ones((4, 2), dtype=np.float32)),
])
def test_corrupt_arrays_are_rejected(key, value):
    schedules, arrays = fixture()
    with pytest.raises(ValueError):
        encode_target_response({**arrays, key: value}, schedules=schedules,
                               source_ids=[10], duration_ms=3)


def test_rejects_unexpected_archive_members():
    schedules, arrays = fixture()
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays, unexpected=np.array([1]))
    with pytest.raises(ValueError, match='archive'):
        decode_target_response(stream.getvalue(), schedules=schedules,
                               source_ids=[10], duration_ms=3)


def test_binary_binds_identity_ids_and_paired_difference():
    schedules, arrays = fixture()
    data = encode_target_response_binary(arrays, schedules=schedules, source_ids=[10],
        duration_ms=3, graph_sha256='a' * 64, configuration_sha256='b' * 64)
    magic, cells, samples, graph_hash, config_hash = struct.unpack('<4sII32s32s', data[:76])
    assert (magic, cells, samples) == (b'FRS1', 2, 4)
    assert graph_hash.hex() == 'a' * 64 and config_hash.hex() == 'b' * 64
    np.testing.assert_array_equal(np.frombuffer(data, dtype='<u8', count=2, offset=76), [20, 30])
    delta = np.frombuffer(data, dtype='<f4', offset=92).reshape(4, 2)
    np.testing.assert_array_equal(
        delta, arrays['active_relative_mv'] - arrays['control_relative_mv']
    )


def test_network_response_roundtrips_all_non_source_cells_and_rejects_missing_cell():
    schedules, arrays = fixture()
    kwargs = {'schedules': schedules, 'source_ids': [10], 'duration_ms': 3,
              'network_ids': np.array([10, 20, 30], dtype=np.int64)}
    data = encode_target_response(arrays, **kwargs)
    np.testing.assert_array_equal(decode_target_response(data, **kwargs)['target_ids'], [20, 30])
    binary = encode_target_response_binary(arrays, **kwargs, graph_sha256='a' * 64,
                                           configuration_sha256='b' * 64)
    assert binary[:4] == b'FRS2'
    with pytest.raises(ValueError):
        decode_target_response(data, **{**kwargs, 'network_ids': np.array([10, 20, 30, 40])})


def test_network_response_encodes_bounded_sample_times(monkeypatch):
    monkeypatch.setattr('service.domain.target_response_limits.MAX_TARGET_RESPONSE_VALUES', 6)
    schedules, arrays = fixture()
    arrays = {**arrays, 'time_ms': np.array([0., 2., 3.], dtype=np.float32),
              'active_relative_mv': arrays['active_relative_mv'][[0, 2, 3]],
              'control_relative_mv': arrays['control_relative_mv'][[0, 2, 3]]}
    kwargs = {'schedules': schedules, 'source_ids': [10], 'duration_ms': 3,
              'network_ids': np.array([10, 20, 30], dtype=np.int64)}
    data = encode_target_response(arrays, **kwargs)
    np.testing.assert_array_equal(decode_target_response(data, **kwargs)['time_ms'], [0, 2, 3])
    binary = encode_target_response_binary(arrays, **kwargs, graph_sha256='a' * 64,
                                           configuration_sha256='b' * 64)
    assert binary[:4] == b'FRS3'
    np.testing.assert_array_equal(np.frombuffer(binary, dtype='<u4', count=3, offset=76), [0, 2, 3])


def test_large_short_capture_is_not_truncated_and_budget_is_explicit():
    ids = np.arange(2, 5002, dtype=np.int64)
    schedules = [{'edge_events': [{'target_id': int(item)} for item in ids]}]
    arrays = {'target_ids': ids, 'time_ms': np.arange(2, dtype=np.float32),
              'active_relative_mv': np.zeros((2, len(ids)), dtype=np.float32),
              'control_relative_mv': np.zeros((2, len(ids)), dtype=np.float32)}
    data = encode_target_response(arrays, schedules=schedules, source_ids=[1], duration_ms=1)
    checked = decode_target_response(data, schedules=schedules, source_ids=[1], duration_ms=1)
    np.testing.assert_array_equal(checked['target_ids'], ids)
    assert can_capture_targets(40000, 99)
    assert not can_capture_targets(40001, 99)
