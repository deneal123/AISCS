import hashlib
import json

import numpy as np
import pytest

pytest.importorskip("neuron")

from service.infrastructure.connectome.morphology_repository import BASE  # noqa: E402
from service.infrastructure.stimulation.swc_reference import (  # noqa: E402
    record_swc_reference,
    record_swc_with_stimulus_artifact,
    simulate_registered_swc_reference,
    simulate_swc_reference,
)

SWC = (
    "1 1 0 0 0 62.5 -1\n2 3 3125 0 0 62.5 1\n3 3 6250 0 0 62.5 2\n"
    "4 3 9375 0 0 62.5 3\n5 3 12500 0 0 62.5 4\n"
    "6 3 6250 3125 0 62.5 3\n"
)


def test_swc_reference_is_repeatable_and_responds_to_the_electrode():
    options = {
        "source_um": [0, 20, 0],
        "return_um": [150, 20, 0],
        "conductivity_s_m": 0.3,
        "clearance_um": 2,
    }
    zero = simulate_swc_reference(SWC, current_na=0, **options)
    active = simulate_swc_reference(SWC, current_na=1000, **options)
    repeat = simulate_swc_reference(SWC, current_na=1000, **options)
    moved = simulate_swc_reference(SWC, current_na=1000, **{**options, "source_um": [-40, 20, 0]})
    assert active["voltage_mv"].shape == (5, 401)
    np.testing.assert_array_equal(active["voltage_mv"], repeat["voltage_mv"])
    np.testing.assert_allclose(zero["field_mv"], 0)
    assert np.max(np.abs(active["voltage_mv"] - zero["voltage_mv"])) > 0.001
    assert np.max(np.abs(active["voltage_mv"] - moved["voltage_mv"])) > 0.001
    assert np.max(np.abs(np.sum(active["membrane_current_na"], axis=0))) < 1e-9


def test_voltage_only_recording_preserves_voltage_and_stimulus():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300,
                   conductivity_s_m=.3, clearance_um=2)
    complete = simulate_swc_reference(SWC, **options)
    screening = simulate_swc_reference(SWC, **options, record_membrane_current=False)
    assert 'membrane_current_na' not in screening
    for key in ('time_ms', 'voltage_mv', 'field_mv', 'stimulus_fraction'):
        np.testing.assert_array_equal(screening[key], complete[key])
    with pytest.raises(ValueError, match='record_membrane_current'):
        simulate_swc_reference(SWC, **options, record_membrane_current=1)


@pytest.mark.parametrize('with_event', [False, True])
def test_zero_stimulus_matches_negligible_driven_control(with_event):
    events = ([{'child_node_id': 3, 'position': .5, 'time_ms': 5., 'weight_us': .001,
                'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}] if with_event else [])
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0],
                   conductivity_s_m=.3, clearance_um=2, synaptic_events=events)
    zero = simulate_swc_reference(SWC, current_na=0., **options)
    negligible = simulate_swc_reference(SWC, current_na=1e-200, **options)
    for key in ('time_ms', 'stimulus_fraction'):
        np.testing.assert_array_equal(zero[key], negligible[key])
    for key in ('voltage_mv', 'membrane_current_na'):
        np.testing.assert_allclose(zero[key], negligible[key], rtol=0, atol=1e-12)


def test_experimental_second_order_is_explicit_and_does_not_leak_between_calls():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300,
                   conductivity_s_m=.3, clearance_um=2)
    baseline = simulate_swc_reference(SWC, **options)
    second_order = simulate_swc_reference(SWC, **options, integration_order=2)
    repeat = simulate_swc_reference(SWC, **options)
    assert np.isfinite(second_order['membrane_current_na']).all()
    np.testing.assert_array_equal(baseline['voltage_mv'], repeat['voltage_mv'])
    np.testing.assert_array_equal(baseline['membrane_current_na'], repeat['membrane_current_na'])
    with pytest.raises(ValueError, match='integration order'):
        simulate_swc_reference(SWC, **options, integration_order=True)


def test_per_edge_resolution_preserves_uniform_solution_and_geometry():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300,
                   conductivity_s_m=.3, clearance_um=2)
    uniform = simulate_swc_reference(SWC, **options, nseg_per_edge=3)
    explicit = simulate_swc_reference(SWC, **options, nseg_by_edge={
        2: 3, 3: 3, 4: 3, 5: 3, 6: 3})
    for key in ('edge_node_ids', 'midpoints_um', 'starts_um', 'ends_um', 'diameters_um',
                'endpoint_radii_um', 'field_mv', 'voltage_mv', 'membrane_current_na'):
        np.testing.assert_array_equal(uniform[key], explicit[key])
    adaptive = simulate_swc_reference(SWC, **options, nseg_by_edge={3: 3, 5: 5})
    restored = simulate_swc_reference(SWC, **options, nseg_by_edge={'3': 3, '5': 5})
    np.testing.assert_array_equal(adaptive['voltage_mv'], restored['voltage_mv'])
    assert adaptive['edge_node_ids'].tolist() == [2, 3, 3, 3, 4, 5, 5, 5, 5, 5, 6]
    assert len(adaptive['midpoints_um']) == 11
    assert np.max(np.abs(np.sum(adaptive['membrane_current_na'], axis=0))) < 1e-9


def test_adaptive_endpoint_relocation_preserves_current_balance():
    from service.infrastructure.stimulation.feedback.endpoint_discretization import (
        discretize_endpoints,
    )

    event = {'child_node_id': 3, 'position': 1., 'time_ms': 5., 'weight_us': .001,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    mapped, proof = discretize_endpoints(
        [event], {3: [[25, 0, 0], [50, 0, 0]]}, nseg_per_edge=5, max_shift_um=2.5)
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=0,
                   conductivity_s_m=.3, clearance_um=2, synaptic_events=mapped)
    adaptive = simulate_swc_reference(SWC, **options, nseg_by_edge={3: 5})
    assert proof[0]['shift_um'] == pytest.approx(2.5)
    assert np.max(adaptive['voltage_mv']) > -20
    assert np.max(np.abs(np.sum(adaptive['membrane_current_na'], axis=0))) < 1e-9


@pytest.mark.parametrize('counts', [{2: 0}, {2: 2}, {2: True}, {999: 3}, {'02': 3},
                                    {2: 3, '2': 5}, []])
def test_per_edge_resolution_rejects_invalid_configuration(counts):
    with pytest.raises(ValueError, match='per-edge'):
        simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 0, .3,
                               clearance_um=2, nseg_by_edge=counts)


@pytest.mark.parametrize('current,shape', [(-300., 'monophasic'), (300., 'monophasic'),
                                           (-300., 'biphasic'), (0., 'monophasic')])
def test_virtual_current_screening_matches_reference_on_branched_swc(current, shape):
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=current,
                   conductivity_s_m=.3, clearance_um=2, pulse_shape=shape,
                   record_membrane_current=False)
    reference = simulate_swc_reference(SWC, **options)
    accelerated = simulate_swc_reference(SWC, **options, field_coupling='virtual_current')
    for key in ('time_ms', 'edge_node_ids', 'field_mv', 'stimulus_fraction'):
        np.testing.assert_array_equal(accelerated[key], reference[key])
    np.testing.assert_allclose(accelerated['voltage_mv'], reference['voltage_mv'],
                               rtol=1e-8, atol=1e-7)


def test_virtual_current_is_not_enabled_for_unvalidated_recordings_or_resolution():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300,
                   conductivity_s_m=.3, clearance_um=2, field_coupling='virtual_current')
    with pytest.raises(ValueError, match='Virtual-current screening'):
        simulate_swc_reference(SWC, **options)
    with pytest.raises(ValueError, match='Virtual-current screening'):
        simulate_swc_reference(SWC, **options, record_membrane_current=False, nseg_per_edge=3)
    with pytest.raises(ValueError, match='Virtual-current screening'):
        simulate_swc_reference(SWC, **options, record_membrane_current=False,
            synaptic_events=[{'child_node_id': 2, 'position': 1., 'time_ms': 5.,
                              'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2.,
                              'reversal_mv': 0.}])


@pytest.mark.parametrize('current', [-300., 0., 300.])
@pytest.mark.parametrize('with_event', [False, True])
@pytest.mark.parametrize('disconnected', [False, True])
def test_experimental_adaptive_virtual_current_matches_reference(current, with_event, disconnected):
    events = ([{'child_node_id': 3, 'position': .9, 'time_ms': 5., 'weight_us': .001,
                'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}] if with_event else [])
    options = dict(source_um=[0, 20, 20], return_um=[150, 20, 20], current_na=current,
                   conductivity_s_m=.3, clearance_um=2, dt_ms=.05, duration_ms=10.,
                   pulse_start_ms=2., pulse_end_ms=3., synaptic_events=events,
                   nseg_per_edge=3, nseg_by_edge={3: 5}, allow_disconnected=disconnected)
    morphology = (SWC + '7 1 0 5000 0 62.5 -1\n8 3 3125 5000 0 75 7\n'
                  if disconnected else SWC)
    reference = simulate_swc_reference(morphology, **options)
    accelerated = simulate_swc_reference(morphology, field_coupling='experimental_virtual_current',
                                          **options)
    for key in ('time_ms', 'edge_node_ids', 'field_mv', 'stimulus_fraction'):
        np.testing.assert_array_equal(accelerated[key], reference[key])
    np.testing.assert_allclose(accelerated['voltage_mv'], reference['voltage_mv'],
                               rtol=0, atol=1e-6)
    np.testing.assert_allclose(accelerated['membrane_current_na'],
                               reference['membrane_current_na'], rtol=0, atol=1e-8)
    points = ([0, 50, 10], [100, 50, 10])
    recorded = record_swc_reference(reference, *points, .3, clearance_um=2)
    candidate = record_swc_reference(accelerated, *points, .3, clearance_um=2)
    np.testing.assert_allclose(candidate, recorded, rtol=0, atol=1e-8)
    for row in (reference['voltage_mv'], accelerated['voltage_mv']):
        assert np.isfinite(row).all()
    expected = (reference['voltage_mv'][:, :-1] < -20) & (reference['voltage_mv'][:, 1:] >= -20)
    actual = (accelerated['voltage_mv'][:, :-1] < -20) & (accelerated['voltage_mv'][:, 1:] >= -20)
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('shape', ['monophasic', 'biphasic'])
@pytest.mark.parametrize('rise', [0., .2])
def test_experimental_coreneuron_matches_reference_and_restores_neuron(shape, rise):
    from neuron import coreneuron, h

    event = {'child_node_id': 3, 'position': .9, 'time_ms': 5., 'weight_us': .001,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    options = dict(source_um=[0, 20, 20], return_um=[150, 20, 20], current_na=-300.,
                   conductivity_s_m=.3, clearance_um=2, dt_ms=.05, duration_ms=10.,
                   pulse_start_ms=2., pulse_end_ms=3., rise_time_ms=rise, pulse_shape=shape,
                   synaptic_events=[event], nseg_by_edge={3: 5})
    reference = simulate_swc_reference(SWC, **options)
    previous_cache = h.CVode().cache_efficient()
    accelerated = simulate_swc_reference(
        SWC, **options, field_coupling='experimental_virtual_current',
        solver_backend='experimental_coreneuron')
    assert not coreneuron.enable and h.CVode().cache_efficient() == previous_cache
    for key in ('time_ms', 'field_mv', 'stimulus_fraction'):
        np.testing.assert_allclose(accelerated[key], reference[key], rtol=0, atol=1e-9)
    np.testing.assert_allclose(accelerated['voltage_mv'], reference['voltage_mv'],
                               rtol=0, atol=1e-6)
    np.testing.assert_allclose(accelerated['membrane_current_na'],
                               reference['membrane_current_na'], rtol=0, atol=1e-8)
    after = simulate_swc_reference(SWC, **options)
    np.testing.assert_array_equal(after['voltage_mv'], reference['voltage_mv'])


def test_experimental_coreneuron_requires_explicit_compatible_mode():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300.,
                   conductivity_s_m=.3, clearance_um=2)
    with pytest.raises(ValueError, match='CoreNEURON requires'):
        simulate_swc_reference(SWC, **options, solver_backend='experimental_coreneuron')
    with pytest.raises(ValueError, match='CoreNEURON requires'):
        simulate_swc_reference(SWC, **options, field_coupling='experimental_virtual_current',
                               solver_backend='experimental_coreneuron', integration_order=2)


def test_experimental_coreneuron_rejects_gpu_and_releases_sections():
    from neuron import coreneuron, h

    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300.,
                   conductivity_s_m=.3, clearance_um=2,
                   field_coupling='experimental_virtual_current',
                   solver_backend='experimental_coreneuron')
    try:
        coreneuron.gpu = True
        with pytest.raises(RuntimeError, match='configured for CPU'):
            simulate_swc_reference(SWC, **options)
        assert not list(h.allsec()) and not coreneuron.enable
    finally:
        coreneuron.gpu = False
    result = simulate_swc_reference(SWC, **options)
    assert np.isfinite(result['voltage_mv']).all()


@pytest.mark.parametrize('position', [0., 1.])
def test_synapses_on_zero_area_section_endpoints_are_rejected(position):
    event = {'child_node_id': 2, 'position': position, 'time_ms': 5., 'weight_us': .001,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    with pytest.raises(ValueError, match='zero-area section endpoint'):
        simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 0., .3,
                               clearance_um=2., synaptic_events=[event])


@pytest.mark.parametrize('nseg', [1, 3, 5])
def test_interior_synapse_preserves_membrane_current_balance(nseg):
    event = {'child_node_id': 3, 'position': .999, 'time_ms': 5., 'weight_us': .001,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    result = simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 0., .3,
                                    clearance_um=2., nseg_per_edge=nseg, synaptic_events=[event])
    assert np.max(result['voltage_mv']) > -20.
    assert np.max(np.abs(np.sum(result['membrane_current_na'], axis=0))) < 1e-9


@pytest.mark.parametrize('method', ['extracellular', 'virtual_current'])
def test_both_field_couplings_reject_contact_intersections(method):
    with pytest.raises(ValueError, match='exclusion'):
        simulate_swc_reference(SWC, [1, 0, 0], [150, 20, 0], -300, .3, clearance_um=.1,
                               record_membrane_current=False, field_coupling=method)


def test_stimulation_contact_and_current_reversal_preserves_the_response():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=-300,
                   conductivity_s_m=.3, clearance_um=2, rise_time_ms=.2)
    original = simulate_swc_reference(SWC, **options)
    switched = simulate_swc_reference(SWC, **{**options,
        'source_um': options['return_um'], 'return_um': options['source_um'],
        'current_na': -options['current_na']})
    inverted = simulate_swc_reference(SWC, **{**options,
        'source_um': options['return_um'], 'return_um': options['source_um']})
    np.testing.assert_array_equal(original['field_mv'], switched['field_mv'])
    np.testing.assert_array_equal(original['voltage_mv'], switched['voltage_mv'])
    np.testing.assert_array_equal(original['membrane_current_na'], switched['membrane_current_na'])
    np.testing.assert_allclose(original['field_mv'], -inverted['field_mv'], atol=1e-12)
    assert np.max(np.abs(original['voltage_mv'] - inverted['voltage_mv'])) > .001


def test_integration_mode_does_not_depend_on_previous_neuron_global_state():
    from neuron import h

    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=.3, clearance_um=2)
    h.secondorder = 0
    baseline = simulate_swc_reference(SWC, **options)
    h.secondorder = 2
    repeat = simulate_swc_reference(SWC, **options)
    assert h.secondorder == 0
    np.testing.assert_array_equal(baseline['voltage_mv'], repeat['voltage_mv'])
    np.testing.assert_array_equal(baseline['membrane_current_na'], repeat['membrane_current_na'])


def test_hh_kinetics_are_explicit_and_restore_the_caller_global_setting():
    from neuron import h

    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=.3, clearance_um=2)
    previous = h.usetable_hh
    try:
        h.usetable_hh = 1
        tabulated = simulate_swc_reference(SWC, **options)
        h.usetable_hh = 0
        repeated = simulate_swc_reference(SWC, **options)
        assert h.usetable_hh == 0
        np.testing.assert_array_equal(tabulated['voltage_mv'], repeated['voltage_mv'])
        np.testing.assert_array_equal(tabulated['membrane_current_na'],
                                      repeated['membrane_current_na'])

        direct = simulate_swc_reference(SWC, **options, experimental_hh_direct=True)
        assert h.usetable_hh == 0
        h.usetable_hh = 1
        direct_repeat = simulate_swc_reference(SWC, **options, experimental_hh_direct=True)
        assert h.usetable_hh == 1
        np.testing.assert_array_equal(direct['voltage_mv'], direct_repeat['voltage_mv'])
        assert not np.array_equal(tabulated['voltage_mv'], direct['voltage_mv'])
        with pytest.raises(ValueError, match='experimental_hh_direct'):
            simulate_swc_reference(SWC, **options, experimental_hh_direct=1)
        with pytest.raises(ValueError, match='CoreNEURON'):
            simulate_swc_reference(SWC, **options, experimental_hh_direct=True,
                                   field_coupling='experimental_virtual_current',
                                   solver_backend='experimental_coreneuron')
    finally:
        h.usetable_hh = previous


def test_hh_kinetics_restore_the_caller_setting_when_the_solver_fails(monkeypatch):
    import neuron

    actual = neuron.h
    previous = actual.usetable_hh

    class FailingHoc:
        def __getattr__(self, name):
            if name == 'continuerun':
                def fail(_duration):
                    raise RuntimeError('solver failed')
                return fail
            return getattr(actual, name)

        def __setattr__(self, name, value):
            setattr(actual, name, value)

    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=.3, clearance_um=2)
    try:
        actual.usetable_hh = 1
        monkeypatch.setattr(neuron, 'h', FailingHoc())
        with pytest.raises(RuntimeError, match='solver failed'):
            simulate_swc_reference(SWC, **options, experimental_hh_direct=True)
        assert actual.usetable_hh == 1
    finally:
        actual.usetable_hh = previous


def test_degenerate_source_geometry_is_not_simulated():
    with pytest.raises(ValueError, match="nonzero"):
        simulate_swc_reference(
            "1 1 0 0 0 1 -1\n2 3 0 0 0 1 1\n", [0, 20, 0], [150, 20, 0], 1, 0.3, clearance_um=2
        )


def test_disconnected_swc_is_not_misrepresented_as_one_neuron():
    disconnected = SWC + "7 1 25000 0 0 62.5 -1\n8 3 28125 0 0 62.5 7\n"
    with pytest.raises(ValueError, match="one connected"):
        simulate_swc_reference(disconnected, [0, 20, 0], [150, 20, 0], 1, 0.3, clearance_um=2)
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=.3, clearance_um=2)
    single = simulate_swc_reference(SWC, **options)
    fragments = simulate_swc_reference(disconnected, **options, allow_disconnected=True)
    np.testing.assert_allclose(fragments["voltage_mv"][:5], single["voltage_mv"], atol=1e-12)
    assert len(fragments["edge_node_ids"]) == 6
    with pytest.raises(ValueError, match="isolated"):
        simulate_swc_reference(SWC + "7 1 25000 0 0 62.5 -1\n", **options,
                               allow_disconnected=True)
    with pytest.raises(ValueError, match="boolean"):
        simulate_swc_reference(SWC, **options, allow_disconnected=1)


def test_stimulation_contact_cannot_intersect_between_segment_midpoints():
    with pytest.raises(ValueError, match="cable segment"):
        simulate_swc_reference(SWC, [1, 0, 0], [150, 20, 0], 1, 0.3, clearance_um=0.1)


def test_reference_membrane_parameters_are_explicit_and_affect_response():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=0.3, clearance_um=2)
    baseline = simulate_swc_reference(SWC, **options)
    altered = simulate_swc_reference(SWC, **options, membrane_capacitance_uf_cm2=2)
    assert np.max(np.abs(baseline['voltage_mv'] - altered['voltage_mv'])) > 0.001
    for value in (0, -1, True, float('nan')):
        with pytest.raises(ValueError, match='membrane parameters'):
            simulate_swc_reference(SWC, **options, membrane_capacitance_uf_cm2=value)


def test_finite_stimulus_ramp_is_recorded_and_invalid_ramps_are_rejected():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=0.3, clearance_um=2)
    result = simulate_swc_reference(SWC, **options, rise_time_ms=.2)
    time, waveform = result["time_ms"], result["stimulus_fraction"]
    np.testing.assert_allclose(waveform[np.argmin(abs(time - 2.1))], .5, atol=.13)
    np.testing.assert_allclose(waveform[np.argmin(abs(time - 2.5))], 1, atol=1e-12)
    for value in (-1, .6, True, float("nan")):
        with pytest.raises(ValueError, match="timing"):
            simulate_swc_reference(SWC, **options, rise_time_ms=value)


def test_two_pulse_solver_and_recording_share_the_verified_waveform():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=300,
                   conductivity_s_m=.3, clearance_um=2, duration_ms=12.,
                   pulse_start_ms=2., pulse_end_ms=3., rise_time_ms=.2,
                   pulse_count=2, pulse_interval_ms=5.)
    solution = simulate_swc_reference(SWC, **options)
    time, stimulus = solution['time_ms'], solution['stimulus_fraction']
    np.testing.assert_allclose(np.interp([1, 2.5, 5, 7.5, 10], time, stimulus),
                               [0, 1, 0, 1, 0], atol=1e-12)
    channel = record_swc_with_stimulus_artifact(solution, {'configuration': options},
                                                [0, 40, 0], [150, 40, 0])
    assert channel['stimulus_artifact_uv'][np.argmin(abs(time - 7.5))] != 0
    bad = {'configuration': {**options, 'pulse_interval_ms': 4.}}
    with pytest.raises(ValueError, match='does not match'):
        record_swc_with_stimulus_artifact(solution, bad, [0, 40, 0], [150, 40, 0])


def test_biphasic_pulse_is_charge_balanced_and_artifact_changes_polarity():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=0.3, clearance_um=2, rise_time_ms=.2,
                   pulse_shape="biphasic", interphase_gap_ms=.5)
    result = simulate_swc_reference(SWC, **options)
    time, waveform = result["time_ms"], result["stimulus_fraction"]
    assert waveform.max() == pytest.approx(1) and waveform.min() == pytest.approx(-1)
    assert abs(np.trapezoid(waveform, time)) < 1e-9
    record = record_swc_with_stimulus_artifact(
        result, {"configuration": options}, [0, 40, 0], [150, 40, 0]
    )
    artifact = record["stimulus_artifact_uv"]
    assert artifact.max() > 0 and artifact.min() < 0
    with pytest.raises(ValueError, match="does not match"):
        record_swc_with_stimulus_artifact(
            result, {"configuration": {**options, "interphase_gap_ms": 1}},
            [0, 40, 0], [150, 40, 0]
        )
    for patch in ({"pulse_shape": "bad"}, {"interphase_gap_ms": -1}, {"duration_ms": 4}):
        with pytest.raises(ValueError, match="timing"):
            simulate_swc_reference(SWC, **{**options, **patch})


def test_refining_branch_segments_converges_for_reference_geometry():
    options = {
        "source_um": [0, 20, 0],
        "return_um": [150, 20, 0],
        "current_na": 1000,
        "conductivity_s_m": 0.3,
        "clearance_um": 2,
    }
    results = [simulate_swc_reference(SWC, nseg_per_edge=n, **options) for n in (1, 3, 9)]
    traces = [
        result["voltage_mv"][2 * n + n // 2] for result, n in zip(results, (1, 3, 9), strict=True)
    ]
    coarse = np.max(np.abs(traces[0] - traces[2]))
    refined = np.max(np.abs(traces[1] - traces[2]))
    assert refined < coarse
    with pytest.raises(ValueError, match="positive odd"):
        simulate_swc_reference(SWC, nseg_per_edge=2, **options)


def test_native_swc_membrane_currents_are_recorded_differentially():
    result = simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 1000, 0.3, clearance_um=2)
    first, second = [0, 40, 0], [150, 40, 0]
    a = record_swc_reference(result, first, second, 0.3, clearance_um=2)
    line = record_swc_reference(result, first, second, 0.3, clearance_um=2,
                                source_model="linesource")
    line_reversed = record_swc_reference(result, second, first, 0.3, clearance_um=2,
                                         source_model="linesource")
    reversed_contacts = record_swc_reference(result, second, first, 0.3, clearance_um=2)
    moved = record_swc_reference(result, [0, 80, 0], second, 0.3, clearance_um=2)
    assert np.isfinite(a).all() and np.max(np.abs(a)) > 0
    assert np.isfinite(line).all() and np.max(np.abs(line - a)) > 0
    np.testing.assert_allclose(line_reversed, -line, atol=1e-12)
    with pytest.raises(ValueError, match="Unknown recording source model"):
        record_swc_reference(result, first, second, 0.3, clearance_um=2, source_model="other")
    np.testing.assert_allclose(reversed_contacts, -a, atol=1e-12)
    assert np.max(np.abs(a - moved)) > 0
    with pytest.raises(ValueError):
        record_swc_reference(result, result["midpoints_um"][0], second, 0.3, clearance_um=2)


def test_recording_rejects_misaligned_and_nonfinite_cell_currents():
    result = simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 1000, 0.3, clearance_um=2)
    for current in (result["membrane_current_na"][:, :1],
                    np.full_like(result["membrane_current_na"], np.nan)):
        with pytest.raises(ValueError, match="Invalid reference recording"):
            record_swc_reference({**result, "membrane_current_na": current},
                                 [0, 40, 0], [150, 40, 0], 0.3, clearance_um=2)
    for corrupt in ({"midpoints_um": result["midpoints_um"] + 1},
                    {"time_ms": result["time_ms"][::-1]},
                    {"diameters_um": result["diameters_um"] * 2}):
        with pytest.raises(ValueError, match="Invalid reference recording"):
            record_swc_reference({**result, **corrupt}, [0, 40, 0], [150, 40, 0], 0.3,
                                 clearance_um=2)


def test_stimulus_artifact_does_not_disappear_on_an_equipotential_neurite():
    swc = "1 1 0 0 0 62.5 -1\n2 3 0 0 12500 62.5 1\n"
    config = dict(source_um=[100, 0, 0], return_um=[-100, 0, 0], current_na=1000,
                  conductivity_s_m=0.3, clearance_um=2)
    result = simulate_swc_reference(swc, **config)
    np.testing.assert_array_equal(result["field_mv"], [0])
    record = record_swc_with_stimulus_artifact(
        result, {"configuration": config}, [100, 50, 0], [-100, 50, 0]
    )
    assert np.max(np.abs(record["stimulus_artifact_uv"])) > 0
    assert np.max(np.abs(record["stimulus_artifact_uv"][result["time_ms"] < 1.9])) == 0
    swapped = {**config, "source_um": config["return_um"], "return_um": config["source_um"]}
    with pytest.raises(ValueError, match="does not match"):
        record_swc_with_stimulus_artifact(
            result, {"configuration": swapped}, [100, 50, 0], [-100, 50, 0]
        )
    with pytest.raises(ValueError, match="does not match"):
        record_swc_with_stimulus_artifact(
            result, {"configuration": {**config, "rise_time_ms": .2}},
            [100, 50, 0], [-100, 50, 0]
        )
    altered = result["stimulus_fraction"].copy()
    altered[10] = 0.5
    with pytest.raises(ValueError, match="waveform does not match"):
        record_swc_with_stimulus_artifact(
            {**result, "stimulus_fraction": altered}, {"configuration": config},
            [100, 50, 0], [-100, 50, 0]
        )
    altered = result["stimulus_fraction"].copy()
    altered[np.argmin(np.abs(result["time_ms"] - 2))] = 0.5
    with pytest.raises(ValueError, match="waveform does not match"):
        record_swc_with_stimulus_artifact(
            {**result, "stimulus_fraction": altered}, {"configuration": config},
            [100, 50, 0], [-100, 50, 0]
        )


def test_explicit_synaptic_event_affects_compartment_currents_after_event():
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=0,
                   conductivity_s_m=0.3, clearance_um=2)
    event = {"child_node_id": 2, "position": .5, "time_ms": 4., "weight_us": .001,
             "tau1_ms": .2, "tau2_ms": 2., "reversal_mv": 0.}
    baseline = simulate_swc_reference(SWC, **options)
    active = simulate_swc_reference(SWC, **options, synaptic_events=[event])
    before = active["time_ms"] < 3.9
    after = active["time_ms"] > 4.1
    np.testing.assert_allclose(active["voltage_mv"][:, before], baseline["voltage_mv"][:, before])
    assert np.max(np.abs(active["voltage_mv"][:, after] - baseline["voltage_mv"][:, after])) > .01
    assert np.max(np.abs(active["membrane_current_na"][:, after]
                         - baseline["membrane_current_na"][:, after])) > 1e-6
    provenance = {"configuration": {**options, "synaptic_events": [event]}}
    record_swc_with_stimulus_artifact(active, provenance, [0, 40, 0], [150, 40, 0])
    altered = {**event, "weight_us": .002}
    with pytest.raises(ValueError, match="Synaptic events"):
        record_swc_with_stimulus_artifact(
            active, {"configuration": {**options, "synaptic_events": [altered]}},
            [0, 40, 0], [150, 40, 0]
        )


@pytest.mark.parametrize("override", [{"child_node_id": 999}, {"time_ms": -1},
                                      {"tau1_ms": 3}, {"tau1_ms": 1.99999},
                                      {"tau1_ms": 1e-12}, {"weight_us": True}])
def test_invalid_synaptic_event_is_rejected(override):
    event = {"child_node_id": 2, "position": .5, "time_ms": 4., "weight_us": .001,
             "tau1_ms": .2, "tau2_ms": 2., "reversal_mv": 0., **override}
    with pytest.raises(ValueError, match="synaptic event"):
        simulate_swc_reference(SWC, [0, 20, 0], [150, 20, 0], 0, .3, clearance_um=2,
                               synaptic_events=[event])


def test_registered_reference_binds_result_to_verified_source(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = SWC.encode()
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / "receipts" / "42.json").write_text(json.dumps({
        "body_id": 42, "url": BASE + "42.swc", "sha256": digest,
    }))
    options = dict(source_um=[0, 20, 0], return_um=[150, 20, 0], current_na=1000,
                   conductivity_s_m=0.3, clearance_um=2)
    result, provenance = simulate_registered_swc_reference(42, [tmp_path], **options)
    assert result["voltage_mv"].shape == (5, 401)
    assert provenance["morphology_sha256"] == digest
    bound_result, bound_provenance = simulate_registered_swc_reference(
        42, [tmp_path], expected_morphology_sha256=digest, **options
    )
    np.testing.assert_array_equal(bound_result["voltage_mv"], result["voltage_mv"])
    assert bound_provenance["morphology_sha256"] == digest
    with pytest.raises(ValueError, match="digest mismatch"):
        simulate_registered_swc_reference(
            42, [tmp_path], expected_morphology_sha256="0" * 64, **options
        )
    assert provenance["body_id"] == "42" and provenance["vertices"] == 6
    assert provenance["components"] == 1
    assert provenance["fragment_interpretation"] == "one connected SWC component"
    assert "not Drosophila calibrated" in provenance["membrane_model"]
    assert provenance["configuration"]["source_um"] == options["source_um"]
    assert provenance["configuration"]["nseg_per_edge"] == 1
    assert 'experimental_hh_direct' not in provenance['configuration']
    assert provenance['fixed_parameters']['hh_kinetics'] == 'tabulated'
    _, direct_provenance = simulate_registered_swc_reference(
        42, [tmp_path], experimental_hh_direct=True, **options)
    assert direct_provenance['configuration']['experimental_hh_direct'] is True
    assert direct_provenance['fixed_parameters']['hh_kinetics'] == 'direct'
    adaptive, adaptive_provenance = simulate_registered_swc_reference(
        42, [tmp_path], nseg_by_edge={3: 3}, **options)
    persisted = json.loads(json.dumps(adaptive_provenance['configuration']))
    assert persisted['nseg_by_edge'] == {'3': 3}
    experimental, experimental_provenance = simulate_registered_swc_reference(
        42, [tmp_path], nseg_by_edge={3: 3},
        field_coupling='experimental_virtual_current', **options)
    assert experimental_provenance['configuration']['field_coupling'] == (
        'experimental_virtual_current')
    recording = record_swc_with_stimulus_artifact(
        experimental, experimental_provenance, [0, 40, 0], [150, 40, 0])
    assert np.isfinite(recording['neural_uv']).all()
    core_result, core_provenance = simulate_registered_swc_reference(
        42, [tmp_path], nseg_by_edge={3: 3}, field_coupling='experimental_virtual_current',
        solver_backend='experimental_coreneuron', **options)
    assert core_provenance['configuration']['solver_backend'] == 'experimental_coreneuron'
    core_recording = record_swc_with_stimulus_artifact(
        core_result, core_provenance, [0, 40, 0], [150, 40, 0])
    np.testing.assert_allclose(core_recording['neural_uv'], recording['neural_uv'],
                               rtol=0, atol=1e-8)
    restored, _ = simulate_registered_swc_reference(42, [tmp_path], **persisted)
    np.testing.assert_array_equal(adaptive['voltage_mv'], restored['voltage_mv'])
    assert 'record_membrane_current' not in provenance['configuration']
    assert 'integration_order' not in provenance['configuration']
    _, second_order_provenance = simulate_registered_swc_reference(
        42, [tmp_path], integration_order=2, **options)
    assert second_order_provenance['configuration']['integration_order'] == 2
    assert second_order_provenance['fixed_parameters']['integration'].endswith('secondorder=2')
    voltage_only, voltage_provenance = simulate_registered_swc_reference(
        42, [tmp_path], record_membrane_current=False, **options)
    assert voltage_provenance['configuration']['record_membrane_current'] is False
    np.testing.assert_array_equal(voltage_only['voltage_mv'], result['voltage_mv'])
    assert provenance["configuration"]["dt_ms"] == 0.025
    assert provenance["configuration"]["membrane_capacitance_uf_cm2"] == 1.0
    assert provenance["configuration"]["temperature_c"] == 23.0
    assert provenance["neuron_version"] and provenance["numpy_version"]
    json.dumps(provenance, allow_nan=False)
    channel = record_swc_with_stimulus_artifact(result, provenance, [0, 40, 0], [150, 40, 0])
    line_channel = record_swc_with_stimulus_artifact(
        result, provenance, [0, 40, 0], [150, 40, 0], source_model="linesource"
    )
    swapped = record_swc_with_stimulus_artifact(result, provenance, [150, 40, 0], [0, 40, 0])
    assert np.max(np.abs(channel["stimulus_artifact_uv"])) > 0
    assert np.max(np.abs(channel["stimulus_artifact_uv"][result["time_ms"] < 1.9])) == 0
    assert np.max(np.abs(channel["stimulus_artifact_uv"][result["time_ms"] > 3.1])) == 0
    expected = 1000 * 1000 / (4 * np.pi * 0.3) * (2 / 20 - 2 / np.hypot(150, 20))
    np.testing.assert_allclose(channel["stimulus_artifact_uv"][100], expected, rtol=1e-12)
    np.testing.assert_allclose(
        channel["total_uv"], channel["neural_uv"] + channel["stimulus_artifact_uv"]
    )
    np.testing.assert_array_equal(
        line_channel["stimulus_artifact_uv"], channel["stimulus_artifact_uv"]
    )
    np.testing.assert_allclose(
        line_channel["total_uv"], line_channel["neural_uv"] + line_channel["stimulus_artifact_uv"]
    )
    np.testing.assert_allclose(swapped["total_uv"], -channel["total_uv"], atol=1e-12)
    corrupted = {**provenance, "configuration": {**provenance["configuration"], "current_na": 500}}
    with pytest.raises(ValueError, match="does not match"):
        record_swc_with_stimulus_artifact(result, corrupted, [0, 40, 0], [150, 40, 0])
    zero, zero_provenance = simulate_registered_swc_reference(
        42, [tmp_path], **{**options, "current_na": 0}
    )
    zero_channel = record_swc_with_stimulus_artifact(
        zero, zero_provenance, [0, 40, 0], [150, 40, 0]
    )
    np.testing.assert_array_equal(
        zero_channel["stimulus_artifact_uv"], np.zeros_like(zero["time_ms"])
    )
    (tmp_path / "raw" / "42.swc").write_bytes(raw + b"tampered")
    with pytest.raises(ValueError, match="failed validation"):
        simulate_registered_swc_reference(42, [tmp_path], **options)
