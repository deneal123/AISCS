import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_nociception_connectivity.py'
spec = importlib.util.spec_from_file_location('nociception_connectivity', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_audit_checks_provenance_and_counts_directed_edges(tmp_path):
    arrays = {'ids': [10, 20, 30], 'ptr': [0, 2, 3, 3],
              'posts': [1, 2, 0], 'counts': [4, 6, 7]}
    hashes = {}
    for name, values in arrays.items():
        path = tmp_path / f'{name}.npy'
        np.save(path, np.array(values))
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    annotations = tmp_path / 'neurons.feather'
    annotations.write_bytes(b'annotations')
    manifest = {'dataset': 'male-cns:v1.0', 'arrays': hashes}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    candidates = tmp_path / 'candidates.json'
    candidates.write_text(json.dumps({'candidates': [{'bodyId': 10}, {'bodyId': 20}],
        'male_cns_annotations_sha256': hashlib.sha256(b'annotations').hexdigest()}))
    result = module.audit(candidates, tmp_path)
    assert result['edges_between_candidates'] == [
        {'source': 10, 'target': 20, 'synapses': 4},
        {'source': 20, 'target': 10, 'synapses': 7},
    ]
    assert result['candidate_outgoing_totals'][10]['outgoing_synapses'] == 10
    annotations.write_bytes(b'different')
    with pytest.raises(ValueError, match='annotations'):
        module.audit(candidates, tmp_path)
