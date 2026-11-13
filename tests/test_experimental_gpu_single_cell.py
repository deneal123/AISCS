import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.single_cell import solve_single_cell


@pytest.fixture
def inputs():
    return {
        'geometry': {'parents': [-1, 0], 'conductances': [0., .5], 'segment_nodes': [1],
                     'area': [1.], 'grid': [(2, 0, 1)]},
        'field_current_na': [0.], 'events': [], 'stimulus_midpoint': [0., 1., 1.],
        'rate_table': np.tile([.5, 1., .5, 1., .5, 1.], (201, 1)),
        'initial_gates': [.5, .5, .5],
    }


@pytest.mark.parametrize(('name', 'value'), [
    ('field_current_na', [float('nan')]),
    ('stimulus_midpoint', [1., 1.]),
    ('initial_gates', [.5, 2., .5]),
    ('initial_voltage_mv', 150.),
])
def test_rejects_invalid_inputs_before_requesting_cuda(inputs, name, value):
    inputs[name] = value
    with pytest.raises(ValueError):
        solve_single_cell(**inputs)


def test_rejects_endpoint_events_before_requesting_cuda(inputs):
    inputs['events'] = [{'child_node_id': 2, 'position': 1., 'time_ms': .025,
                         'weight_us': .1, 'tau1_ms': .1, 'tau2_ms': 1.,
                         'reversal_mv': 0.}]
    with pytest.raises(ValueError, match='Unsupported event'):
        solve_single_cell(**inputs)
