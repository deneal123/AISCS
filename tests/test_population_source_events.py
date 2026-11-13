import hashlib
import json
import struct
from uuid import uuid4

import numpy as np
import pytest

from service.infrastructure.stimulation.population.source_events import (
    HEADER,
    encode_population_source_events,
)
from tests.test_population_feedback_http import configuration
from tests.test_population_feedback_validation import example_result


def test_encodes_unique_candidate_crossings_without_network_spikes():
    result, graph, _ = example_result()
    physical = result['physical_source_output']
    physical['candidate_events_by_source'][10].append({
        'partner_id': '20', 'source_position_8nm': [7, 8, 9], 'stimulated_ticks_ms': [1, 3]})
    encoded = encode_population_source_events(physical, graph, duration_ms=10,
                                              configuration_sha256='d' * 64)
    magic, nodes, duration, count, graph_hash, config_hash = HEADER.unpack_from(encoded)
    assert (magic, nodes, duration, count) == (b'SRC1', 3, 10, 2)
    assert graph_hash.hex() == 'a' * 64 and config_hash.hex() == 'd' * 64
    assert np.frombuffer(encoded, dtype='<u4', count=count, offset=HEADER.size).tolist() == [0, 0]
    times = np.frombuffer(encoded, dtype='<u4', count=count, offset=HEADER.size + 4 * count)
    assert times.tolist() == [1, 3]
    assert len(encoded) == struct.calcsize('<4sIII32s32s') + 8 * count


def test_rejects_unknown_population_and_invalid_ticks():
    result, graph, _ = example_result()
    physical = result['physical_source_output']
    physical['candidate_events_by_source'][10][0]['stimulated_ticks_ms'] = [11]
    with pytest.raises(ValueError, match='ticks'):
        encode_population_source_events(physical, graph, duration_ms=10,
                                        configuration_sha256='d' * 64)


@pytest.mark.parametrize('corruption', ['unknown', 'duplicate', 'negative', 'unsorted', 'identity'])
def test_rejects_invalid_provenance_or_source_events(corruption):
    result, graph, _ = example_result()
    physical = result['physical_source_output']
    if corruption == 'unknown':
        physical['source_ids'] = [10, 999]
        physical['candidate_events_by_source'][999] = physical['candidate_events_by_source'].pop(20)
    elif corruption == 'duplicate':
        physical['source_ids'] = [10, 10]
    elif corruption == 'negative':
        physical['candidate_events_by_source'][10][0]['stimulated_ticks_ms'] = [0]
    elif corruption == 'unsorted':
        physical['candidate_events_by_source'][10][0]['stimulated_ticks_ms'] = [3, 1]
    else:
        physical['graph_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        encode_population_source_events(physical, graph, duration_ms=10,
                                        configuration_sha256='d' * 64)


@pytest.mark.parametrize('status', ['converged', 'iteration_limit', 'cycle_detected'])
@pytest.mark.parametrize('refined', [False, True])
def test_executor_publishes_source_markers_from_verified_feedback(tmp_path, monkeypatch, status,
                                                                  refined):
    from service.infrastructure.execution.process import run_population_feedback_child

    result, graph, source = example_result()
    result['status'] = status
    result['iterations'][0].update(input_events=2, unresolved_events=0, outside_window=0,
                                   output_edge_records=1, network_spikes=0)
    monkeypatch.setenv('GENERATOR_SYNAPSE_DIR', str(tmp_path))
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: graph)
    monkeypatch.setattr('service.infrastructure.connectome.synapse_repository.registered_index',
                        lambda *_: object())
    monkeypatch.setattr('service.settings.connectome_directory', lambda: tmp_path)
    monkeypatch.setattr('service.settings.morphology_directories', lambda: [])
    monkeypatch.setattr('service.infrastructure.stimulation.population.transport.'
                        'unpack_fragment_population', lambda *_: source)
    calls = []
    def iterate(*_args, **kwargs):
        calls.append(kwargs)
        return result
    monkeypatch.setattr('service.application.feedback.loop.iterate_population_feedback',
                        iterate)
    monkeypatch.setattr('service.application.feedback.preview.population_feedback_preview',
                        lambda *_: {'kind': 'test'})
    archive_contexts = []
    def write_archive(_result, path, **kwargs):
        archive_contexts.append(kwargs['discretization_context'])
        path.write_bytes(b'archive')
        return 'e' * 64
    def read_archive(*_args, **kwargs):
        archive_contexts.append(kwargs['discretization_context'])
        return result
    monkeypatch.setattr('service.infrastructure.stimulation.feedback.archive.'
                        'write_population_feedback', write_archive)
    monkeypatch.setattr('service.infrastructure.stimulation.feedback.archive.'
                        'read_population_feedback', read_archive)
    monkeypatch.setattr('service.infrastructure.stimulation.population.sparse_delta.encode_sparse_delta',
                        lambda *_, **_kw: b'delta')
    monkeypatch.setattr('service.infrastructure.connectome.forced_export.encode_forced_spikes',
                        lambda *_: (b'events', None, 'f' * 64))
    target = tmp_path / 'output'
    config = configuration()
    if refined:
        config['discretization'] = {'max_shift_um': 2., 'max_observation_distance_um': 2.,
                                    'max_nseg': 9}
    payload = {'execution_id': str(uuid4()), 'config': config}
    if status != 'converged':
        with pytest.raises(ValueError, match=f'Coupled feedback did not converge: {status}'):
            run_population_feedback_child(payload, str(target), str(tmp_path))
        assert not (target / 'manifest.json').exists()
        error = json.loads((target / 'error.json').read_text(encoding='utf-8'))
        assert error['type'] == 'ValueError'
        assert error['message'] == f'Coupled feedback did not converge: {status}'
        assert error['feedback_diagnostics'] == {'status': status, 'history': [{
            'iteration': 1, 'input_events': 2, 'unresolved_events': 0, 'outside_window': 0,
            'output_edge_records': 1, 'network_spikes': 0}]}
        assert ('discretization_policy' in calls[0]) is refined
        return
    run_population_feedback_child(payload, str(target), str(tmp_path))
    assert ('discretization_policy' in calls[0]) is refined
    assert len(archive_contexts) == 2
    assert all((context is not None) is refined for context in archive_contexts)
    if refined:
        assert archive_contexts[0]['policy'] == calls[0]['discretization_policy']
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    entry = next(row for row in manifest['files'] if row['name'] == 'coupled-source-events.bin')
    data = (target / entry['name']).read_bytes()
    assert HEADER.unpack_from(data)[0] == b'SRC1'
    assert entry['sha256'] == hashlib.sha256(data).hexdigest()
