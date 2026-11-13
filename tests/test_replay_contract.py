import pytest
from pydantic import ValidationError

from service.domain.contracts.replay import ReplayRunConfig


def valid():
    return {'source_run_id': '00000000-0000-4000-8000-000000000001',
            'graph_manifest_sha256': 'a' * 64, 'body_id': 12781,
            'synapse': {'delay_ms': 2., 'weight_us': .00001, 'tau1_ms': .2,
                        'tau2_ms': 2., 'reversal_mv': 0.},
            'simulation': {'source_um': [1., 2., 3.], 'return_um': [2., 2., 3.],
                           'electrode_um': [1., 2., 4.], 'reference_um': [2., 2., 4.],
                           'current_na': 0., 'conductivity_s_m': .3, 'clearance_um': 1.,
                           'duration_ms': 65., 'dt_ms': .05, 'pulse_start_ms': 2.,
                           'pulse_end_ms': 3., 'rise_time_ms': .2, 'interphase_gap_ms': .5,
                           'pulse_shape': 'biphasic', 'nseg_per_edge': 1,
                           'allow_disconnected': True, 'source_model': 'pointsource',
                           'coordinate_frame': 'male-cns-v1.0-native-um'}}


def test_valid_contract_hash_is_stable():
    original = valid()
    a = ReplayRunConfig.model_validate(original)
    b = ReplayRunConfig.model_validate(dict(reversed(list(original.items()))))
    assert a.digest() == b.digest() and len(a.digest()) == 64
    original['synapse']['weight_us'] *= 2
    assert ReplayRunConfig.model_validate(original).digest() != a.digest()


def test_execution_parameters_keep_recording_separate_from_stimulation():
    config = ReplayRunConfig.model_validate(valid())
    plan = config.execution_parameters()
    assert plan['body_id'] == 12781
    assert plan['schedule_parameters']['duration_ms'] == 65.
    assert plan['electrode_um'] == (1., 2., 4.)
    assert plan['simulation_parameters']['source_um'] == (1., 2., 3.)
    assert 'electrode_um' not in plan['simulation_parameters']
    assert plan['configuration_sha256'] == config.digest()


@pytest.mark.parametrize('section,key,value', [
    ('synapse', 'weight_us', True), ('synapse', 'tau1_ms', 1.99999),
    ('simulation', 'current_na', float('nan')), ('simulation', 'dt_ms', .07),
    ('simulation', 'nseg_per_edge', 2), ('simulation', 'allow_disconnected', 1),
    ('simulation', 'reference_um', [1., 2., 4.]), ('simulation', 'coordinate_frame', 'body'),
])
def test_invalid_scientific_configuration_is_rejected(section, key, value):
    item = valid()
    item[section][key] = value
    with pytest.raises(ValidationError):
        ReplayRunConfig.model_validate(item)


def test_path_and_unknown_inputs_are_rejected():
    item = valid()
    item['path'] = '/arbitrary/file'
    with pytest.raises(ValidationError):
        ReplayRunConfig.model_validate(item)
