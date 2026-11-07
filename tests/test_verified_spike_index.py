from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.stimulation.synaptic_replay import select_recorded_spikes
from service.infrastructure.stimulation.verified_spike_index import VerifiedSpikeIndex


def fixture():
    rng = np.random.default_rng(42)
    graph = SimpleNamespace(ids=np.arange(1, 501, dtype=np.int64),
                            provenance={"manifest_sha256": "graph"})
    times = np.sort(rng.integers(1, 101, 4000)).astype(np.float32)
    neurons = rng.integers(0, len(graph.ids), len(times), dtype=np.int32)
    binary, description, sha = encode_forced_spikes(graph, {
        "spike_neurons": neurons, "spike_times_ms": times,
        "metadata": {"graph": graph.provenance, "duration_ms": 100}})
    return graph, neurons, times, binary, description, sha


def test_index_matches_reference_for_many_partner_groups_and_time_windows():
    graph, neurons, times, binary, description, sha = fixture()
    index = VerifiedSpikeIndex(binary, description, sha, graph.ids, "graph")
    rng = np.random.default_rng(3)
    for _ in range(30):
        partners = rng.choice(graph.ids, 15, replace=False).tolist()
        assert index.select(partners) == select_recorded_spikes(graph.ids, neurons, times, partners)
    for duration, delay in ((100, 2), (50, 0), (10, 4)):
        expected = {int(graph.ids[i]) for i in neurons[times.astype(float) + delay < duration]}
        assert index.active_before(duration, delay) == expected
    assert index.select([]) == {}


def test_index_rejects_corrupt_source_and_invalid_requests():
    graph, _, _, binary, description, sha = fixture()
    with pytest.raises(ValueError, match="checksum"):
        VerifiedSpikeIndex(binary + b"x", description, sha, graph.ids, "graph")
    with pytest.raises(ValueError, match="version"):
        VerifiedSpikeIndex(binary, description, sha, graph.ids, "wrong")
    index = VerifiedSpikeIndex(binary, description, sha, graph.ids, "graph")
    for invalid in ([1, 1], [True], [0], [[1]]):
        with pytest.raises(ValueError, match="partner IDs"):
            index.select(invalid)
    with pytest.raises(ValueError, match="missing"):
        index.select([501])
    with pytest.raises(ValueError, match="time window"):
        index.active_before(101, 0)
