import numpy as np
import pytest

from service.application.population.bulk_simulation_inputs import bulk_simulation_inputs
from tests.test_fragment_population_contract import example


def test_experiment_configuration_maps_to_gpu_waveform_and_contacts():
    simulation = example()['simulation']
    result = bulk_simulation_inputs(simulation)
    assert result['params'].source_um == tuple(simulation['source_um'])
    assert result['electrode_um'] == simulation['electrode_um']
    assert result['reference_um'] == simulation['reference_um']
    assert len(result['stimulus']) == len(result['time_ms']) == 201
    assert result['stimulus'][0] == 0
    assert np.isclose(result['stimulus'][41], .125)
    assert result['stimulus'][45] == 1
    assert result['time_ms'][-1] == 10


@pytest.mark.parametrize('change', [
    {'source_model': 'linesource'}, {'dt_ms': .1}, {'allow_disconnected': False},
])
def test_unsupported_gpu_configuration_fails_closed(change):
    with pytest.raises(ValueError):
        bulk_simulation_inputs({**example()['simulation'], **change})


def test_duration_is_bounded_before_allocating_the_waveform():
    simulation = {**example()['simulation'], 'duration_ms': 2001.0}
    with pytest.raises(ValueError, match='40000-step'):
        bulk_simulation_inputs(simulation)
