import copy
import hashlib

import numpy as np
import pytest

from service.infrastructure.connectome.forced_network import contrast_forced_network
from service.infrastructure.connectome.state_contrast_export import (
    decode_state_contrast,
    encode_state_contrast,
)
from tests.test_forced_network import graph


def example():
    model = graph()
    model.provenance['manifest_sha256'] = 'a' * 64
    result = contrast_forced_network(model, seed=1, duration_ms=6, forced_cell_ids=[10],
                                     events={10: [1]}, sample_cell_ids=[30, 20])
    result['provenance'] = {'field_manifest_sha256': 'b' * 64,
                            'graph_manifest_sha256': 'a' * 64, 'graph_sha256': 'c' * 64}
    data, description = encode_state_contrast(result)
    expected = {'expected_field_manifest_sha256': 'b' * 64,
                'expected_graph_manifest_sha256': 'a' * 64,
                'expected_graph_sha256': 'c' * 64, 'graph_ids': model.ids}
    return result, data, description, expected


def test_round_trip_preserves_order_and_model_state():
    result, data, description, expected = example()
    restored = decode_state_contrast(data, description, **expected)
    np.testing.assert_array_equal(restored['cell_ids'], [30, 20])
    np.testing.assert_array_equal(restored['time_ms'], result['sampled_time_ms'])
    np.testing.assert_array_equal(restored['voltage_difference_mv'],
                                  result['voltage_difference_mv'])


def test_decoder_rejects_tampering_and_wrong_run():
    _, data, description, expected = example()
    with pytest.raises(ValueError):
        decode_state_contrast(data + b'x', description, **expected)
    for key in ('expected_field_manifest_sha256', 'expected_graph_manifest_sha256',
                'expected_graph_sha256'):
        with pytest.raises(ValueError):
            decode_state_contrast(data, description, **{**expected, key: 'd' * 64})
    invalid = copy.deepcopy(description)
    invalid['difference_shape'] = [2, 7]
    with pytest.raises(ValueError):
        decode_state_contrast(data, invalid, **expected)


def test_decoder_rejects_unknown_cells_and_nonfinite_values_even_with_matching_hash():
    _, data, description, expected = example()
    altered = bytearray(data)
    altered[:8] = (40).to_bytes(8, 'little')
    changed = {**description, 'sha256': hashlib.sha256(altered).hexdigest()}
    with pytest.raises(ValueError, match='cells or values'):
        decode_state_contrast(bytes(altered), changed, **expected)
    altered = bytearray(data)
    altered[description['difference_offset']:description['difference_offset'] + 4] = (
        np.array([np.nan], dtype='<f4').tobytes())
    changed['sha256'] = hashlib.sha256(altered).hexdigest()
    with pytest.raises(ValueError, match='cells or values'):
        decode_state_contrast(bytes(altered), changed, **expected)


def test_encoder_rejects_a_fabricated_difference():
    result, _, _, _ = example()
    result['voltage_difference_mv'][0, 0] = 1
    with pytest.raises(ValueError, match='Invalid state contrast'):
        encode_state_contrast(result)
