import numpy as np
import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.experimental_gpu.cached_geometry import cached_cable_inputs


def entry():
    return {'skeleton': {'body_id': '17', 'sha256': 'a' * 64,
                         'source': f'{BASE}17.swc', 'source_units': '8 nm'},
            'geometry': (np.array([40, 10, 20]), np.array([[1., 2., 3.], [2., 2., 3.],
                                                          [3., 2., 3.]]),
                         np.array([-1, 0, 1]), np.array([.1, .2, .3]))}


def test_conversion_preserves_order_and_source_geometry():
    nodes, edges, components = cached_cable_inputs(entry(), body_id=17, expected_sha256='a' * 64)
    assert list(nodes) == [40, 10, 20]
    assert edges == [(10, 40), (20, 10)]
    assert components == 1
    np.testing.assert_array_equal(nodes[10][0], [2., 2., 3.])


def test_source_mismatch_and_disconnected_cycle_are_rejected():
    with pytest.raises(ValueError, match='source mismatch'):
        cached_cable_inputs(entry(), body_id=17, expected_sha256='b' * 64)
    value = entry()
    value['geometry'] = (*value['geometry'][:2], np.array([-1, 2, 1]), value['geometry'][3])
    with pytest.raises(ValueError, match='Cyclic'):
        cached_cable_inputs(value, body_id=17, expected_sha256='a' * 64)
