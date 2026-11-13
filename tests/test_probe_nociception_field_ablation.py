import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_nociception_field_ablation.py'
spec = importlib.util.spec_from_file_location('nociception_ablation', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_masks_partition_field_and_keep_seed_and_conditions(tmp_path, monkeypatch):
    sensory, ascending = tmp_path / 'sensory.json', tmp_path / 'ascending.json'
    sensory.write_text(json.dumps({'male_cns_annotations_sha256': 'x',
                                   'candidates': [{'bodyId': 10}]}))
    ascending.write_text(json.dumps({'male_cns_annotations_sha256': 'x',
                                    'candidates': [{'bodyId': 20}]}))
    graph = SimpleNamespace(ids=np.array([10, 20]), ptr=np.array([0, 2, 3]),
                            posts=np.array([0, 1, 0]),
                            counts=np.array([4, 5, 6]),
                            provenance={'annotations_sha256': 'x', 'manifest_sha256': 'g'})
    monkeypatch.setattr(module, 'load_registered_graph', lambda _: graph)
    monkeypatch.setattr(module, 'verified_descriptors', lambda *a, **kw: (
        np.array([2., 3.]), {'file_sha256': 'f', 'field_audit': {'configuration': {}},
                            'excluded_from_direct_field': [],
                            'excluded_contact_intersections': []}))
    calls = []

    def run(_graph, *, descriptor, waveform, gain, seed):
        calls.append((descriptor.copy(), waveform, gain, seed, _graph.counts.copy()))
        return {'counts': np.array([0, 0]), 'spike_neurons': np.array([], dtype=np.int32),
                'spike_times_ms': np.array([], dtype=np.float32)}

    monkeypatch.setattr(module, 'run_field_proxy', run)
    report = module.probe(tmp_path, tmp_path / 'field', sensory, ascending, 3., 4)
    assert list(report['results']) == ['all', 'candidate_only', 'candidate_only_no_outgoing',
                                       'candidate_only_no_direct_ascending',
                                       'without_candidates', 'zero']
    assert [call[0].tolist() for call in calls] == [
        [2, 3], [2, 0], [2, 0], [2, 0], [0, 3], [0, 0]]
    assert all(call[2:4] == (3., 4) and call[1] == calls[0][1] for call in calls)
    assert calls[2][4].tolist() == [0, 0, 6]
    assert calls[3][4].tolist() == [4, 0, 6]
    assert graph.counts.tolist() == [4, 5, 6]


def test_timeline_groups_only_selected_cells():
    run = {'spike_neurons': np.array([0, 1, 1, 2]),
           'spike_times_ms': np.array([3., 4., 4., 5.])}
    assert module.event_timeline(run, np.array([1])) == [{'time_ms': 4., 'events': 2}]
