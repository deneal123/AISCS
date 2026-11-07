import copy
import hashlib
import json

import numpy as np
import pytest

from service.application.feedback.population_feedback_validation import validate_population_feedback
from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from tests.test_forced_network import graph
from tests.test_population_feedback_checkpoint import sample


def example_result():
    config, diagnostics, state = sample()
    network_graph = graph()
    network_graph.provenance = {'manifest_sha256': config.graph_manifest_sha256}
    for row in diagnostics.values():
        row['morphology_sha256'] = 'b' * 64
    schedule = {'source_ids': config.source_ids, 'graph_sha256': config.graph_manifest_sha256,
                'events_by_target': {10: [], 20: []}, 'unresolved': []}
    payload = {'events': schedule['events_by_target'], 'unresolved': []}
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode()).hexdigest()
    state['history'][0]['schedule_sha256'] = signature
    source = {'metadata': {'configuration': config.model_dump(mode='json'),
                           'diagnostics': list(diagnostics.values())},
              'manifest': {'configuration_sha256': config.digest(),
                           'graph_sha256': config.graph_manifest_sha256}}
    result = {'status': 'converged', 'feedback_alignment': 'schedule_matches_last_replay',
              'iterations': state['history'], 'recording': state['recording'],
              'schedule': schedule,
              'physical_source_output': {'source_ids': [10, 20],
                  'graph_sha256': config.graph_manifest_sha256,
                  'source_configuration_sha256': config.digest(),
                  'threshold_mv': config.threshold_mv,
                  'source_morphology_sha256': {10: 'b' * 64, 20: 'b' * 64},
                  'candidate_events_by_source': {int(k): v for k, v in state['local'].items()},
                  'edge_events': state['edges']},
              'network': {'forced_cell_ids': [10, 20],
                  'metadata': {'graph': network_graph.provenance, 'seed': config.seed,
                               'duration_ms': config.simulation.duration_ms},
                  'final_voltage_relative_mv': np.zeros(3, dtype=np.float32),
                  'final_synaptic_drive_mv': np.zeros(3, dtype=np.float32),
                  'spike_neurons': np.array([2], dtype=np.int32),
                  'spike_times_ms': np.array([5.], dtype=np.float32),
                  'counts': np.array([0, 0, 1], dtype=np.int32),
                  'sparse_delta': {'status': 'recorded',
                      'offsets': np.zeros(12, dtype=np.uint32),
                      'indices': np.array([], dtype=np.int32),
                      'values': np.array([], dtype=np.float32)}}}
    return result, network_graph, source


def validate(result, network_graph, source):
    return validate_population_feedback(result, network_graph, source,
        parameters={1: {'weight_us': .001}}, allow_partial_geometry=False)


def test_validates_aligned_population_and_network():
    result, network_graph, source = example_result()
    assert validate(result, network_graph, source) is result


def test_source_geometry_gap_requires_partial_status_and_provenance():
    result, network_graph, source = example_result()
    source['metadata']['configuration']['allow_partial_geometry'] = True
    config = FragmentPopulationConfig.model_validate(source['metadata']['configuration'])
    source['manifest']['configuration_sha256'] = config.digest()
    source['metadata']['diagnostics'][0]['candidates'][0]['centerline_distance_um'] = .1
    source['metadata']['diagnostics'][1]['candidates'][0]['centerline_distance_um'] = 2.1
    source['metadata']['schedules'] = [{'unresolved_geometry': []},
                                       {'unresolved_geometry': [{'candidate_index': 0}]}]
    physical = result['physical_source_output']
    physical['source_configuration_sha256'] = config.digest()
    physical['source_unresolved_graph_pairs'] = 1
    physical['candidate_events_by_source'][20] = []
    result['status'] = 'converged_partial'
    params = {1: {'weight_us': .001}}
    assert validate_population_feedback(result, network_graph, source, parameters=params,
                                        allow_partial_geometry=True) is result
    result['status'] = 'converged'
    with pytest.raises(ValueError, match='identity'):
        validate_population_feedback(result, network_graph, source, parameters=params,
                                     allow_partial_geometry=True)


@pytest.mark.parametrize('case', ['unconverged', 'schedule', 'edge', 'forced_spike', 'counts',
                                  'missing_full_graph', 'morphology'])
def test_rejects_inconsistent_coupled_result(case):
    result, network_graph, source = example_result()
    result = copy.deepcopy(result)
    if case == 'unconverged':
        result['status'] = 'iteration_limit'
    elif case == 'schedule':
        result['schedule']['events_by_target'][10].append({'time_ms': 2})
    elif case == 'edge':
        result['physical_source_output']['edge_events'][0]['count'] = 2
    elif case == 'forced_spike':
        result['network']['spike_neurons'][0] = 0
    elif case == 'counts':
        result['network']['counts'][2] = 2
    elif case == 'missing_full_graph':
        result['network']['sparse_delta'] = {'status': 'limit_exceeded'}
    else:
        result['physical_source_output']['source_morphology_sha256'][10] = 'c' * 64
    with pytest.raises(ValueError):
        validate(result, network_graph, source)
