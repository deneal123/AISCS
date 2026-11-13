import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.stimulation.population.pair_mapping import (
    schedule_population_fragment_events,
)
from service.infrastructure.stimulation.recording.verified_target_archive import (
    read_target_replay,
    write_target_replay,
)


def result_fixture():
    return {'source_configuration_sha256': 'a' * 64,
            'source_manifest': {'kind': 'experimental-fragment-population',
                                'configuration_sha256': 'a' * 64, 'graph_sha256': 'b' * 64},
            'source_population_ids': [1],
            'selected_source_ids': [1], 'schedule_parameters': [{}],
            'max_target_distance_um': 2, 'max_events': 10, 'interpretation': 'limited',
            'recording': {'source_cells': 1, 'target_cells': 1,
                'time_ms': [0, 1], 'source_neural_uv': [1, 2],
                'target_neural_uv': [4, 5], 'neural_uv': [5, 7],
                'stimulus_artifact_uv': [0, 3], 'total_uv': [5, 10]},
            'replay': {'baseline_neural_uv': [3, 3], 'delta_neural_uv': [1, 2],
                'mapping': {'target_id': 2, 'source_ids': [1], 'graph_sha256': 'b' * 64,
                            'target_morphology_sha256': 'c' * 64},
                'schedule': {'target_id': 2, 'source_ids': [1], 'graph_sha256': 'b' * 64,
                             'target_morphology_sha256': 'c' * 64, 'events': []}, 'recording': {},
                'voltage_range_mv': {}, 'baseline_provenance': {}, 'active_provenance': {},
                'interpretation': 'one-way'}}


def test_target_archive_round_trip_and_refuses_overwrite(tmp_path):
    target = tmp_path / 'target'
    manifest = write_target_replay(result_fixture(), target)
    stored = read_target_replay(target)
    assert stored['manifest'] == manifest
    assert stored['metadata']['selected_source_ids'] == [1]
    assert stored['preview']['source_cells'] == 1
    assert stored['preview']['target_id'] == 2
    np.testing.assert_array_equal(stored['arrays']['total_uv'], [5, 10])
    with pytest.raises(FileExistsError):
        write_target_replay(result_fixture(), target)
    (target / 'target-signals.npz').write_bytes(b'altered')
    with pytest.raises(ValueError, match='artifact'):
        read_target_replay(target)


def test_voltage_probe_round_trip_and_identity_check(tmp_path):
    result = result_fixture()
    result['replay']['schedule']['events'] = [{'child_node_id': 9, 'position': .7}]
    result['replay']['voltage_probe'] = {
        'child_node_id': 9, 'segment_index': 2, 'segments_per_edge': 3,
        'segment_center': 2.5 / 3, 'time_ms': [0, 1], 'baseline_mv': [-65, -64],
        'active_mv': [-65, -20],
        'interpretation': 'first matched event compartment; uncalibrated model voltage'}
    target = tmp_path / 'target'
    write_target_replay(result, target)
    stored = read_target_replay(target)
    np.testing.assert_array_equal(stored['arrays']['probe_active_mv'], [-65, -20])
    assert stored['preview']['voltage_probe']['child_node_id'] == 9
    assert stored['preview']['probe_morphology_sha256'] == 'c' * 64
    assert stored['preview']['probe_baseline_mv'] == [-65, -64]
    result['replay']['voltage_probe']['segment_index'] = 1
    with pytest.raises(ValueError, match='probe'):
        write_target_replay(result, tmp_path / 'invalid')


@pytest.mark.parametrize(('mode', 'arrival'), [('upper_bound', 4.15), ('lower_bound', 4.1)])
def test_bound_schedule_persists_and_rejects_changed_timing(tmp_path, mode, arrival):
    result = result_fixture()
    result['schedule_parameters'] = [{'duration_ms': 10, 'delay_ms': 1., 'weight_us': .001,
                                      'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}]
    sources = [{'source_id': 1, 'target_id': 2, 'graph_sha256': 'b' * 64,
                'target_morphology_sha256': 'c' * 64,
                'candidates': [{'target_child_node_id': 9, 'target_fraction': .5,
                                'stimulated_ticks_ms': [4],
                                'stimulated_crossing_intervals': [
                                    {'lower_ms': 3.1, 'upper_ms': 3.15, 'tick_ms': 4}]}]}]
    result['replay']['mapping']['sources'] = sources
    result['replay']['schedule'] = schedule_population_fragment_events(
        sources, result['schedule_parameters'], max_events=10, timing_mode=mode)
    target = tmp_path / 'target'
    write_target_replay(result, target)
    assert read_target_replay(target)['preview']['timing_mode'] == mode
    result['replay']['schedule']['events'][0]['time_ms'] = 5.
    with pytest.raises(ValueError, match='time mismatch'):
        write_target_replay(result, tmp_path / 'invalid')
    result['replay']['schedule']['events'][0]['time_ms'] = arrival
    result['replay']['schedule']['events'][0]['child_node_id'] = 10
    with pytest.raises(ValueError, match='provenance mismatch'):
        write_target_replay(result, tmp_path / 'invalid-compartment')
    result['replay']['schedule']['events'][0]['child_node_id'] = 9
    result['replay']['schedule']['events'][0]['weight_us'] = .002
    with pytest.raises(ValueError, match='provenance mismatch'):
        write_target_replay(result, tmp_path / 'invalid-parameters')


def test_inconsistent_signal_and_invalid_manifest_are_rejected(tmp_path):
    result = result_fixture()
    result['recording']['total_uv'] = [5, 11]
    with pytest.raises(ValueError, match='Inconsistent'):
        write_target_replay(result, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()
    (tmp_path / 'manifest.json').write_text(json.dumps([]), encoding='utf8')
    with pytest.raises(ValueError, match='manifest'):
        read_target_replay(tmp_path)


def test_metadata_inconsistency_is_rejected_even_with_updated_file_hash(tmp_path):
    target = tmp_path / 'target'
    write_target_replay(result_fixture(), target)
    path = target / 'target-model.json'
    model = json.loads(path.read_text(encoding='utf8'))
    model['selected_source_ids'] = [99]
    data = json.dumps(model).encode('utf8')
    path.write_bytes(data)
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    manifest['files'][0]['bytes'] = len(data)
    manifest['files'][0]['sha256'] = hashlib.sha256(data).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='metadata'):
        read_target_replay(target)


def test_execution_provenance_is_bound_to_the_manifest(tmp_path):
    target = tmp_path / 'target'
    provenance = {'configuration_sha256': 'd' * 64, 'source_package_sha256': 'e' * 64,
                  'source_manifest_sha256': 'f' * 64}
    write_target_replay(result_fixture(), target, execution_provenance=provenance)
    assert read_target_replay(target)['metadata']['execution'] == provenance
    path = target / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['configuration_sha256'] = '0' * 64
    path.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='execution provenance'):
        read_target_replay(target)


def test_preview_must_match_signal_even_if_file_hash_is_updated(tmp_path):
    target = tmp_path / 'target'
    write_target_replay(result_fixture(), target)
    path = target / 'target-preview.json'
    preview = json.loads(path.read_text(encoding='utf8'))
    preview['neural_uv'][0] += 1
    data = json.dumps(preview).encode('utf8')
    path.write_bytes(data)
    path = target / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['files'][2]['bytes'] = len(data)
    manifest['files'][2]['sha256'] = hashlib.sha256(data).hexdigest()
    path.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='preview mismatch'):
        read_target_replay(target)
