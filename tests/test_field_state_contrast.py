import hashlib
import json

import numpy as np
import pytest

from service.application.field.state_contrast import contrast_verified_field_run
from service.infrastructure.stimulation.field.graph_export import export_field_graph_replay
from tests.test_field_graph_export import example


def saved_run(tmp_path):
    graph, result, evidence, provenance = example()
    result['configuration']['seed'] = 1
    path = tmp_path / 'run'
    export_field_graph_replay(result, graph, path, evidence=evidence, provenance=provenance)
    return graph, path


def contrast(path, graph, ids):
    return contrast_verified_field_run(path, graph, sample_cell_ids=ids,
        expected_manifest_sha256=hashlib.sha256((path / 'manifest.json').read_bytes()).hexdigest())


def test_saved_field_run_produces_matching_seeded_contrast(tmp_path):
    graph, path = saved_run(tmp_path)
    result = contrast(path, graph, [20, 30])
    assert result['provenance']['field_manifest_sha256'] == hashlib.sha256(
        (path / 'manifest.json').read_bytes()).hexdigest()
    np.testing.assert_array_equal(result['sampled_time_ms'], np.arange(7))
    np.testing.assert_array_equal(result['active_spike_neurons'], [0, 1, 2])
    np.testing.assert_array_equal(result['active_spike_times_ms'], [1, 3, 5])
    assert np.any(result['voltage_difference_mv'] != 0)


def test_saved_field_run_rejects_an_untrusted_manifest(tmp_path):
    graph, path = saved_run(tmp_path)
    with pytest.raises(ValueError, match='trusted digest'):
        contrast_verified_field_run(path, graph, sample_cell_ids=[20],
                                    expected_manifest_sha256='0' * 64)


def test_saved_field_run_rejects_tampered_artifact(tmp_path):
    graph, path = saved_run(tmp_path)
    with (path / 'graph.bin').open('ab') as output:
        output.write(b'x')
    with pytest.raises(ValueError, match='checksum'):
        contrast(path, graph, [20])


def test_saved_field_run_rejects_graph_that_cannot_reproduce_events(tmp_path):
    graph, path = saved_run(tmp_path)
    meta_path = path / 'metadata.json'
    metadata = json.loads(meta_path.read_text())
    metadata['configuration']['seed'] = 13
    meta_path.write_text(json.dumps(metadata))
    manifest_path = path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest['files']:
        if entry['name'] == 'metadata.json':
            data = meta_path.read_bytes()
            entry['sha256'], entry['bytes'] = hashlib.sha256(data).hexdigest(), len(data)
    manifest_path.write_text(json.dumps(manifest))
    # A seed can coincidentally produce the same spikes for a tiny graph; compare
    # against a deliberately changed signed graph instead to force disagreement.
    graph.signs[0] = -1
    with pytest.raises(ValueError, match='Recomputed graph events'):
        contrast(path, graph, [20])
