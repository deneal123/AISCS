import numpy as np

from service.application.feedback.population_feedback_preview import population_feedback_preview
from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from tests.test_fragment_population_contract import example
from tests.test_population_feedback_validation import example_result


def test_preview_uses_physical_recording_and_network_spikes():
    result, graph, _source = example_result()
    for key in ('time_ms', 'neural_uv', 'total_uv', 'stimulus_fraction'):
        result['recording'][key] = np.asarray(result['recording'][key])
    config = FragmentPopulationConfig.model_validate(example())
    preview = population_feedback_preview(result, graph, config)
    assert preview['source_ids'] == [10, 20]
    assert preview['graph_cells'] == 3
    assert [preview['timeline']['time_ms'][0], preview['timeline']['time_ms'][-1]] == [0., 10.]
    assert [preview['timeline']['neural_uv'][0], preview['timeline']['neural_uv'][-1]] == [1., 2.]
    assert preview['timeline']['network_spikes_by_ms'][5] == 1
    assert sum(preview['timeline']['network_spikes_by_ms']) == preview['network_spikes']


def test_preview_discloses_unresolved_source_geometry():
    result, graph, _source = example_result()
    for key in ('time_ms', 'neural_uv', 'total_uv', 'stimulus_fraction'):
        result['recording'][key] = np.asarray(result['recording'][key])
    result['physical_source_output']['source_unresolved_graph_pairs'] = 3
    result['status'] = 'converged_partial'
    config = FragmentPopulationConfig.model_validate({**example(), 'allow_partial_geometry': True})
    preview = population_feedback_preview(result, graph, config)
    assert preview['source_unresolved_graph_pairs'] == 3
    assert preview['unresolved_candidates'] == 0
    assert preview['status'] == 'converged_partial'


def test_preview_reports_bounded_endpoint_refinement():
    result, graph, _source = example_result()
    for key in ('time_ms', 'neural_uv', 'total_uv', 'stimulus_fraction'):
        result['recording'][key] = np.asarray(result['recording'][key])
    result['discretization_receipt'] = {'observation_audit': {'verified_events': 2}, 'targets': {
        10: {'evidence': [
            {'requires_endpoint_relocation': True, 'shift_um': .4,
             'observation_distance_um': .7},
            {'requires_endpoint_relocation': False, 'shift_um': 3.,
             'observation_distance_um': .8}]}}}
    config = FragmentPopulationConfig.model_validate(example())
    preview = population_feedback_preview(result, graph, config)
    assert preview['geometry_discretization'] == {'checked_events': 2, 'relocated_endpoints': 1,
        'max_shift_um': .4, 'max_observation_distance_um': .8}
