import numpy as np
import pytest

from service.application.field.driven_network import run_field_driven_network
from tests.test_forced_network import graph


def test_selected_cell_trace_drives_graph_and_preserves_evidence(monkeypatch):
    def simulate(body, _directories, **settings):
        trace = [-65, -60, -10, -60, -65, -65, -65]
        if not settings['current_na']:
            trace = [-65] * 7
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2]),
                 'voltage_mv': np.array([trace])},
                {'body_id': str(body), 'morphology_sha256': 'a' * 64, 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    args = dict(cells=[{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}], seed=1)
    active = run_field_driven_network(graph(), [], simulation_parameters={
        'duration_ms': 6, 'current_na': 1}, **args)
    control = run_field_driven_network(graph(), [], simulation_parameters={
        'duration_ms': 6, 'current_na': 0}, **args)
    np.testing.assert_array_equal(active['sources'][0]['event_ticks_ms'], [2])
    np.testing.assert_array_equal(active['network']['spike_times_ms'], [2, 4, 6])
    assert control['network']['counts'].sum() == 0
    assert active['sources'][0]['provenance']['morphology_sha256'] == 'a' * 64
    assert active['sources'][0]['crossing_diagnostics']['selected_crossings'] == 1
    assert active['sources'][0]['crossing_diagnostics']['earliest_crossing_sample_ms'] == 2


def test_optional_spatial_crossings_use_same_solution_without_changing_network(monkeypatch):
    def simulate(body, _directories, **_settings):
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2, 3]),
                 'midpoints_um': np.array([[1., 2., 3.], [4., 5., 6.]]),
                 'voltage_mv': np.array([[-65, -60, -10, -60, -65, -65, -65],
                                         [-65, -10, -65, -65, -65, -65, -65]])},
                {'body_id': str(body), 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    args = dict(cells=[{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}], seed=1,
                simulation_parameters={'duration_ms': 6})
    plain = run_field_driven_network(graph(), [], **args)
    saved = run_field_driven_network(graph(), [], retain_compartment_crossings=True, **args)
    np.testing.assert_array_equal(plain['network']['counts'], saved['network']['counts'])
    events = saved['sources'][0]['compartment_crossings']
    np.testing.assert_array_equal(events['compartment_indices'], [0, 1])
    np.testing.assert_array_equal(events['sample_indices'], [2, 1])


def test_source_compartment_must_be_explicit_and_unique(monkeypatch):
    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        lambda *_args, **_kwargs: ({'time_ms': np.arange(7.),
                            'edge_node_ids': np.array([2, 2]),
                            'voltage_mv': np.full((2, 7), -65.)},
                           {'body_id': '10', 'components': 1}))
    with pytest.raises(ValueError, match='ambiguous'):
        run_field_driven_network(graph(), [], cells=[{
            'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
            simulation_parameters={'duration_ms': 6}, seed=1)


@pytest.mark.parametrize('components', [None, True, 0, 2])
def test_fragmented_or_unverified_source_cannot_drive_graph(monkeypatch, components):
    provenance = {'body_id': '10'}
    if components is not None:
        provenance['components'] = components
    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        lambda *_args, **_kwargs: ({'time_ms': np.arange(7.),
                            'edge_node_ids': np.array([2]),
                            'voltage_mv': np.full((1, 7), -65.)}, provenance))
    with pytest.raises(ValueError, match='one connected component'):
        run_field_driven_network(graph(), [], cells=[{
            'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
            simulation_parameters={'duration_ms': 6, 'allow_disconnected': True}, seed=1)


def test_candidate_morphology_identity_is_bound_to_solver_input(monkeypatch):
    def simulate(body, _directories, **settings):
        assert settings['expected_morphology_sha256'] == 'a' * 64
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2]),
                 'voltage_mv': np.full((1, 7), -65.)},
                {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'components': 1})

    monkeypatch.setattr(
        'service.application.field.driven_network.simulate_registered_swc_reference', simulate
    )
    with pytest.raises(ValueError, match='digest mismatch'):
        run_field_driven_network(graph(), [], cells=[{'body_id': 10, 'child_node_id': 2,
            'threshold_mv': -20, 'morphology_sha256': 'a' * 64}],
            simulation_parameters={'duration_ms': 6}, seed=1)


def test_source_time_grids_must_match(monkeypatch):
    def simulate(body, _directories, **_settings):
        time = np.arange(7.) if body == 10 else np.linspace(0, 6, 13)
        return ({'time_ms': time, 'edge_node_ids': np.array([2]),
                 'voltage_mv': np.full((1, len(time)), -65.)},
                {'body_id': str(body), 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    cells = [{'body_id': body, 'child_node_id': 2, 'threshold_mv': -20} for body in [10, 20]]
    with pytest.raises(ValueError, match='time grids'):
        run_field_driven_network(graph(), [], cells=cells,
                                 simulation_parameters={'duration_ms': 6}, seed=1)


def test_spatial_refinement_uses_the_same_edge_midpoint(monkeypatch):
    def simulate(body, _directories, **_settings):
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2, 2, 2]),
                 'voltage_mv': np.array([[-500] * 7, [-65, -60, -10, -60, -65, -65, -65],
                                         [-65] * 7])}, {'body_id': str(body), 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    result = run_field_driven_network(graph(), [], cells=[{
        'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}], seed=1,
        simulation_parameters={'duration_ms': 6, 'nseg_per_edge': 3})
    assert result['sources'][0]['sampling']['edge_fraction'] == 0.5
    assert result['sources'][0]['sampling']['result_segment_index'] == 1
    assert result['sources'][0]['all_voltage_range_mv'] == {'minimum': -500, 'maximum': -10}
    np.testing.assert_array_equal(result['sources'][0]['event_ticks_ms'], [2])


def test_nonfinite_voltage_in_unselected_compartment_is_rejected(monkeypatch):
    def simulate(body, _directories, **_settings):
        voltage = np.full((3, 7), -65.)
        voltage[0, 3] = np.nan
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2, 2, 2]),
                 'voltage_mv': voltage}, {'body_id': str(body), 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    with pytest.raises(ValueError, match='voltage dimensions'):
        run_field_driven_network(graph(), [], cells=[{
            'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}], seed=1,
            simulation_parameters={'duration_ms': 6, 'nseg_per_edge': 3})


def test_requested_fraction_uses_and_records_nearest_segment_centre(monkeypatch):
    def simulate(body, _directories, **_settings):
        return ({'time_ms': np.arange(7.), 'edge_node_ids': np.array([2, 2, 2]),
                 'voltage_mv': np.array([[-65] * 7, [-65] * 7,
                                         [-65, -60, -10, -60, -65, -65, -65]])},
                {'body_id': str(body), 'components': 1})

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    result = run_field_driven_network(graph(), [], cells=[{
        'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20, 'sampling_fraction': .9}], seed=1,
        simulation_parameters={'duration_ms': 6, 'nseg_per_edge': 3})
    sample = result['sources'][0]['sampling']
    assert sample['requested_edge_fraction'] == .9
    assert sample['edge_fraction'] == pytest.approx(5 / 6)
    assert sample['result_segment_index'] == 2
    np.testing.assert_array_equal(result['sources'][0]['event_ticks_ms'], [2])


def test_recording_uses_same_solutions_as_events_and_adds_artifact_once(monkeypatch):
    from service.infrastructure.stimulation.swc_reference import record_swc_with_stimulus_artifact
    from tests.test_network_recording import pair

    solutions = {10: pair(10), 20: pair(20, 1250)}
    calls = []

    def simulate(body, _directories, **_settings):
        calls.append(body)
        return solutions[body]

    monkeypatch.setattr('service.application.field.driven_network.simulate_registered_swc_reference',
                        simulate)
    e1, ref = [0, 200, 0], [200, 200, 0]
    result = run_field_driven_network(graph(), [], cells=[
        {'body_id': body, 'child_node_id': 2, 'threshold_mv': -20} for body in [10, 20]],
        simulation_parameters={'duration_ms': 10}, seed=1,
        recording={'electrode_um': e1, 'reference_um': ref, 'source_model': 'pointsource'},
        acquisition={'low_hz': 100, 'high_hz': 3000, 'recovery_ms': .5, 'clip_uv': .001})
    channels = [record_swc_with_stimulus_artifact(*solutions[body], e1, ref) for body in [10, 20]]
    np.testing.assert_allclose(result['recording']['neural_uv'],
                               channels[0]['neural_uv'] + channels[1]['neural_uv'])
    np.testing.assert_array_equal(result['recording']['stimulus_artifact_uv'],
                                  channels[0]['stimulus_artifact_uv'])
    assert calls == [10, 20] and result['recording']['cells'] == 2
    acquired = result['acquisition']
    np.testing.assert_array_equal(acquired['raw_total_uv'], result['recording']['total_uv'])
    assert acquired['saturated_samples'].any()
    assert not acquired['valid_samples'][np.flatnonzero(acquired['saturated_samples'])[0]:].any()
    assert acquired['recording_provenance']['cells'] == 2


def test_acquisition_needs_explicit_recording():
    with pytest.raises(ValueError, match='requires a recording'):
        run_field_driven_network(graph(), [], cells=[{
            'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
            simulation_parameters={'duration_ms': 10}, seed=1,
            acquisition={'low_hz': 100, 'high_hz': 3000, 'recovery_ms': 0, 'clip_uv': None})


@pytest.mark.parametrize('cells,parameters', [
    ([], {'duration_ms': 6}),
    ([{'body_id': 10, 'child_node_id': 2, 'threshold_mv': True}], {'duration_ms': 6}),
    ([{'body_id': 40, 'child_node_id': 2, 'threshold_mv': -20}], {'duration_ms': 6}),
    ([{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}], {'duration_ms': 6.5}),
    ([{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
     {'duration_ms': 6, 'nseg_per_edge': 2}),
    ([{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
     {'duration_ms': 6, 'nseg_per_edge': True}),
    ([{'body_id': 10, 'child_node_id': 2, 'threshold_mv': -20}],
     {'duration_ms': 6, 'synaptic_events': []}),
])
def test_unsupported_conditions_fail_before_numerics(cells, parameters):
    with pytest.raises(ValueError):
        run_field_driven_network(graph(), [], cells=cells, simulation_parameters=parameters, seed=1)
