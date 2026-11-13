import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_nociception_proxy_response  # noqa: E402


def test_requires_matching_graph_and_paired_control(tmp_path):
    graph = tmp_path / 'graph'
    result = tmp_path / 'result'
    graph.mkdir()
    result.mkdir()
    ids = graph / 'ids.npy'
    np.save(ids, np.array([10, 20]))
    (graph / 'neurons.feather').write_bytes(b'annotations')
    manifest = {'dataset': 'male-cns:v1.0',
                'arrays': {'ids.npy': hashlib.sha256(ids.read_bytes()).hexdigest()}}
    (graph / 'manifest.json').write_text(json.dumps(manifest))
    candidates = tmp_path / 'candidates.json'
    candidates.write_text(json.dumps({'candidates': [{'bodyId': 20}],
        'male_cns_annotations_sha256': hashlib.sha256(b'annotations').hexdigest()}))
    np.savez(result / 'network.npz', counts=[0, 2], control_counts=[0, 1])
    metadata = {'graph_sha256': hashlib.sha256((graph / 'manifest.json').read_bytes()).hexdigest(),
        'network_sha256': hashlib.sha256((result / 'network.npz').read_bytes()).hexdigest(),
        'field': {'field_audit': {'configuration': {}}, 'excluded_from_direct_field': []},
        'gain': 1, 'seed': 1, 'waveform': [0, 1]}
    (result / 'metadata.json').write_text(json.dumps(metadata))
    report = audit_nociception_proxy_response.audit(candidates, graph, result)
    assert report['candidates'] == [{'bodyId': 20, 'events': 2, 'control_events': 1}]
    np.savez(result / 'network.npz', counts=[0, 2])
    with pytest.raises(ValueError, match='provenance'):
        audit_nociception_proxy_response.audit(candidates, graph, result)
    metadata['network_sha256'] = hashlib.sha256((result / 'network.npz').read_bytes()).hexdigest()
    (result / 'metadata.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='control'):
        audit_nociception_proxy_response.audit(candidates, graph, result)
