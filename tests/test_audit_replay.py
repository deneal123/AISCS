import pytest

from scripts.audit_replay import audit
from service.infrastructure.stimulation.replay_export import export_reference_replay


def example():
    event = {'child_node_id': 3, 'position': .5, 'time_ms': 4., 'weight_us': .01,
             'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    return {'mapping': {'body_id': '42', 'direction': 'incoming',
                        'complete_graph_edge_coverage': True,
                        'candidates': [{'partner_id': '11', 'child_node_id': 3,
                                        'segment_fraction': .5}]},
            'selected_spikes': {'11': [2.]}, 'spikes_after_replay_window': 0,
            'connectome_sha256': 'a' * 64,
            'provenance': {'configuration': {'duration_ms': 10., 'synaptic_events': [event]}},
            'replay': {'events': [event], 'event_sources': [{'candidate_index': 0,
                       'presynaptic_id': '11', 'spike_index': 0, 'spike_time_ms': 2.}]},
            'recording_configuration': {'electrode_um': [0., 1., 2.]},
            'interpretation': 'one-way replay', 'solution': {'time_ms': [0., 1., 2.]},
            'channel': {'neural_uv': [1., 2., 3.], 'stimulus_artifact_uv': [1., 0., -1.],
                        'total_uv': [2., 2., 2.]}}


def test_audits_links_to_candidates_and_spikes(tmp_path):
    export_reference_replay(example(), tmp_path)
    result = audit(tmp_path)
    assert result['events'] == 1 and result['delay_ms'] == 2.
    assert result['edge_coverage'] is True


def test_detects_self_consistent_hashes_with_incorrect_event_source(tmp_path):
    result = example()
    result['replay']['event_sources'][0]['spike_time_ms'] = 3.
    export_reference_replay(result, tmp_path)
    with pytest.raises(ValueError, match='does not match source'):
        audit(tmp_path)
