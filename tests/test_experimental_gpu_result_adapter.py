import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.result_adapter import as_reference_arrays


@pytest.fixture
def inputs():
    geometry = {'starts_um': [[0., 0., 0.]], 'ends_um': [[2., 0., 0.]],
                'midpoints_um': [[1., 0., 0.]], 'endpoint_radii_um': [[1., 1.]],
                'diameters_um': [2.], 'edge_node_ids': [42]}
    cell = {'voltage_mv': [[-65., -60.]], 'membrane_current_na': [[0., .1]]}
    return geometry, cell, [0., .025]


def test_reference_arrays_preserve_identifiers_and_traces(inputs):
    geometry, cell, time = inputs
    output = as_reference_arrays(geometry, cell, time)
    np.testing.assert_array_equal(output['edge_node_ids'], [42])
    np.testing.assert_array_equal(output['voltage_mv'], [[-65., -60.]])
    assert 'provenance' not in output


@pytest.mark.parametrize('field', ['midpoints_um', 'edge_node_ids', 'voltage_mv'])
def test_reference_arrays_reject_inconsistent_data(inputs, field):
    geometry, cell, time = inputs
    if field == 'midpoints_um':
        geometry[field] = [[10., 0., 0.]]
    elif field == 'edge_node_ids':
        geometry[field] = [0]
    else:
        cell[field] = [[float('nan'), 0.]]
    with pytest.raises(ValueError):
        as_reference_arrays(geometry, cell, time)
