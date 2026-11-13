import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_nociception_response.py'
spec = importlib.util.spec_from_file_location('nociception_response', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_inputs(tmp_path):
    graph = tmp_path / 'ids.npy'
    np.save(graph, np.array([10, 20, 30]))
    candidates = tmp_path / 'candidates.json'
    candidates.write_text(json.dumps({'male_cns_annotations_sha256': 'annotations',
                                      'candidates': [{'bodyId': 10}, {'bodyId': 30}]}))
    model = {'status': 'converged_partial', 'forced_cell_ids': [10],
             'network_metadata': {'duration_ms': 2, 'graph': {
                 'annotations_sha256': 'annotations',
                 'array_sha256': {'ids.npy': hashlib.sha256(graph.read_bytes()).hexdigest()}}}}
    arrays_buffer = io.BytesIO()
    np.savez(arrays_buffer, sparse_offsets=[0, 0, 1, 2], sparse_indices=[2, 2],
             sparse_values=[-0.2, 0.4], network_counts=[0, 0, 2])
    files = {'model.json': json.dumps(model).encode(), 'arrays.npz': arrays_buffer.getvalue()}
    manifest = {'kind': 'experimental-coupled-population', 'files': [
        {'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()]}
    archive = tmp_path / 'result.zip'
    with zipfile.ZipFile(archive, 'w') as handle:
        handle.writestr('manifest.json', json.dumps(manifest))
        for name, data in files.items():
            handle.writestr(name, data)
    return candidates, graph, archive


def test_candidate_response_and_forced_source_are_distinct(tmp_path):
    candidates, graph, archive = make_inputs(tmp_path)
    result = module.audit(candidates, graph, archive)
    first, second = result['candidates']
    assert first['forced_source'] and first['max_abs_saved_delta_mv'] == 0
    assert not second['forced_source'] and second['network_spikes'] == 2
    assert second['max_abs_saved_delta_mv'] == pytest.approx(0.4)
    assert second['first_changed_saved_tick_ms'] == 1


def test_rejects_mismatched_graph(tmp_path):
    candidates, graph, archive = make_inputs(tmp_path)
    np.save(graph, np.array([10, 20, 31]))
    with pytest.raises(ValueError, match='Candidate missing|provenance mismatch'):
        module.audit(candidates, graph, archive)
