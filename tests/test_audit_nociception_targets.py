import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_nociception_targets  # noqa: E402


def test_ranks_ascending_targets_and_preserves_directed_inputs(tmp_path):
    arrays = {'ids': [10, 20, 30], 'ptr': [0, 2, 3, 3],
              'posts': [1, 2, 1], 'counts': [4, 6, 7]}
    hashes = {}
    for name, values in arrays.items():
        path = tmp_path / f'{name}.npy'
        np.save(path, np.array(values))
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    annotations = tmp_path / 'neurons.feather'
    feather.write_feather(pa.table({'bodyId': [10, 20, 30],
        'superclass': ['vnc_sensory', 'ascending_neuron', 'vnc_motor'],
        'type': [None, 'test', None], 'mancBodyid': [1, 2, None],
        'mancGroup': [None, 2, None], 'mancType': [None, 'A', None]}), annotations)
    (tmp_path / 'manifest.json').write_text(json.dumps({'dataset': 'male-cns:v1.0',
                                                       'arrays': hashes}))
    candidates = tmp_path / 'candidates.json'
    candidates.write_text(json.dumps({'candidates': [{'bodyId': 10, 'mancBodyid': 1}],
        'male_cns_annotations_sha256': hashlib.sha256(annotations.read_bytes()).hexdigest()}))
    result = audit_nociception_targets.audit(candidates, tmp_path)
    assert result['target_count'] == 1
    target = result['targets'][0]
    assert target['bodyId'] == 20 and target['total_synapses_from_candidates'] == 4
    assert target['total_sensory_synapses'] == 4
    assert target['total_incoming_synapses'] == 11
    assert target['candidate_share_sensory'] == 1.0
    assert target['candidate_share_all'] == 4 / 11
    assert target['inputs'] == [{'source_bodyId': 10, 'source_mancBodyid': 1, 'synapses': 4}]
    assert target['edges_ge_4_synapses'] == 1
