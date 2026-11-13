import pytest
from pydantic import ValidationError

from service.domain.contracts.field.proxy import (
    FieldProxyConfig,
    from_fragment_population,
    from_simulation,
)
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from tests.test_fragment_population_contract import example


def valid():
    return {'graph_manifest_sha256': 'a' * 64, 'coordinate_frame': 'male-cns-v1.0-native-um',
            'source_um': [0., 0., 0.], 'return_um': [10., 0., 0.], 'current_na': -300.,
            'conductivity_s_m': .3, 'clearance_um': 1., 'gain': 1., 'seed': 1,
            'waveform': [0., 1., 0.], 'allow_partial_geometry': False,
            'allow_missing_curvature': False}


def test_configuration_is_path_free_and_identity_changes_with_contacts():
    one = FieldProxyConfig.model_validate(valid())
    changed = FieldProxyConfig.model_validate({**valid(), 'source_um': [1., 0., 0.]})
    assert one.digest() != changed.digest()
    assert one.field_configuration()['source_um'] == [0., 0., 0.]
    with pytest.raises(ValidationError):
        FieldProxyConfig.model_validate({**valid(), 'path': '/tmp/input'})


def test_proxy_derives_same_contacts_and_integrated_stimulus_from_physical_run():
    physical = FragmentPopulationConfig.model_validate(example())
    proxy = from_fragment_population(physical, gain=1., allow_partial_geometry=True,
                                     allow_missing_curvature=True, allow_contact_exclusion=False)
    assert proxy.source_um == physical.simulation.source_um
    assert proxy.return_um == physical.simulation.return_um
    assert proxy.current_na == physical.simulation.current_na
    assert proxy.seed == physical.seed
    assert proxy.waveform == pytest.approx([0, 0, .8, 0, 0, 0, 0, 0, 0, 0])
    direct = from_simulation(
        physical.simulation, graph_manifest_sha256=physical.graph_manifest_sha256,
        seed=physical.seed, gain=1., allow_partial_geometry=True,
        allow_missing_curvature=True, allow_contact_exclusion=False,
    )
    assert direct == proxy
    with pytest.raises(ValueError, match='Validated'):
        from_fragment_population(example(), gain=1., allow_partial_geometry=True,
                                 allow_missing_curvature=True, allow_contact_exclusion=False)


def test_proxy_rejects_biphasic_pulse_that_cancels_inside_a_network_tick():
    data = example()
    data['simulation'].update(pulse_start_ms=2.1, pulse_end_ms=2.3, rise_time_ms=0.,
                              pulse_shape='biphasic', interphase_gap_ms=0.)
    physical = FragmentPopulationConfig.model_validate(data)
    with pytest.raises(ValueError, match='unresolved'):
        from_fragment_population(physical, gain=1., allow_partial_geometry=True,
                                 allow_missing_curvature=True, allow_contact_exclusion=False)
    data['simulation']['current_na'] = 0.
    control = FragmentPopulationConfig.model_validate(data)
    projected = from_fragment_population(control, gain=1., allow_partial_geometry=True,
        allow_missing_curvature=True, allow_contact_exclusion=False)
    assert projected.waveform == pytest.approx([0.] * 10)


@pytest.mark.parametrize('change', [
    {'return_um': [1., 0., 0.]}, {'waveform': [1.01]}, {'waveform': []},
    {'current_na': float('nan')}, {'seed': True}, {'allow_partial_geometry': 1},
])
def test_reject_invalid_configuration(change):
    with pytest.raises(ValidationError):
        FieldProxyConfig.model_validate({**valid(), **change})
