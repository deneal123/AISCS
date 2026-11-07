import hashlib
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.replay.population_replay import replay_independent_population
from service.infrastructure.stimulation.swc_reference import record_swc_with_stimulus_artifact
from tests.test_network_recording import pair


@pytest.fixture(autouse=True)
def fake_verified_index(monkeypatch):
    class FakeIndex:
        def __init__(self, *_args):
            pass

        def active_before(self, *_args):
            return set()

    monkeypatch.setattr('service.application.replay.population_replay.VerifiedSpikeIndex', FakeIndex)


def params():
    return {'binary': b'recording', 'description': {}, 'expected_sha256': 'b' * 64,
            'schedule_parameters': {}, 'simulation_parameters': {},
            'electrode_um': [0, 200, 0], 'reference_um': [200, 200, 0]}


def result(body_id, cell):
    solution, provenance = cell
    return {'solution': solution, 'provenance': provenance,
            'mapping': {'body_id': str(body_id), 'complete_graph_edge_coverage': True},
            'selected_spikes': {}, 'spikes_after_replay_window': 0,
            'connectome_sha256': 'b' * 64, 'replay': {'events': [], 'event_sources': []},
            'recording_configuration': {}, 'interpretation': 'one-way replay'}


def test_population_replays_each_cell_and_adds_stimulation_artifact_once(monkeypatch):
    cells = {1: pair(1), 2: pair(2, 1250)}
    calls = []

    def replay(_index, _graph, body_id, _directories, **_kwargs):
        calls.append(body_id)
        return result(body_id, cells[body_id])

    monkeypatch.setattr('service.application.replay.population_replay._execute_preverified_incoming_replay',
                        replay)
    evidence, provenance = io.BytesIO(), io.BytesIO()
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={'manifest_sha256': 'graph'})
    combined = replay_independent_population(None, graph, [1, 2], [], **params(),
                                             evidence_sink=evidence, provenance_sink=provenance)
    channels = [record_swc_with_stimulus_artifact(*cells[i], [0, 200, 0], [200, 200, 0])
                for i in [1, 2]]
    np.testing.assert_allclose(combined['neural_uv'], sum(x['neural_uv'] for x in channels))
    np.testing.assert_array_equal(combined['stimulus_artifact_uv'],
                                  channels[0]['stimulus_artifact_uv'])
    assert calls == [1, 2] and combined['cells'] == 2
    voltage_range = combined['all_voltage_range_mv']
    assert voltage_range['minimum'] <= voltage_range['maximum']
    assert combined['replay_evidence_sha256'] == hashlib.sha256(evidence.getvalue()).hexdigest()
    identities = [json.loads(line)['mapping']['body_id']
                  for line in evidence.getvalue().splitlines()]
    assert identities == ['1', '2']
    assert combined['complete_incoming_graph_coverage']
    assert combined['replay_evidence_exported'] and combined['cell_provenance_exported']


@pytest.mark.parametrize('ids', [[], [1, 1], [True], [3]])
def test_population_rejects_duplicate_or_unregistered_ids(ids):
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={'manifest_sha256': 'graph'})
    with pytest.raises(ValueError):
        replay_independent_population(None, graph, ids, [], **params())


def test_population_rejects_misidentified_cell_and_incomplete_evidence(monkeypatch):
    cell = pair(1)
    graph = SimpleNamespace(ids=np.array([1]), provenance={'manifest_sha256': 'graph'})
    monkeypatch.setattr('service.application.replay.population_replay._execute_preverified_incoming_replay',
                        lambda *_args, **_kwargs: result(2, cell))
    with pytest.raises(ValueError, match='wrong neuron'):
        replay_independent_population(None, graph, [1], [], **params())

    class BrokenSink:
        def write(self, payload):
            return len(payload) - 1

    monkeypatch.setattr('service.application.replay.population_replay._execute_preverified_incoming_replay',
                        lambda *_args, **_kwargs: result(1, cell))
    with pytest.raises(OSError, match='evidence'):
        replay_independent_population(None, graph, [1], [], **params(), evidence_sink=BrokenSink())
