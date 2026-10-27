import numpy as np
import pytest

from service.infrastructure.connectome.dataset import load_registered_graph
from service.infrastructure.connectome.kernel import advance, signed_weights


def test_sparse_wave_obeys_real_edges_and_two_millisecond_delivery():
    ptr = np.array([0, 1, 2, 2], dtype=np.int64)
    posts = np.array([1, 2], dtype=np.int32)
    weights = signed_weights(ptr, np.array([200, 200]), np.ones(3), 1.0)
    voltage, current = np.zeros(3, np.float32), np.zeros(3, np.float32)
    refractory, queue = np.zeros(3, np.int16), np.zeros((3, 3), np.float32)
    first = {}
    for clock in range(5):
        counts = advance(
            ptr,
            posts,
            weights,
            voltage,
            current,
            refractory,
            queue,
            clock,
            np.array([200, 0, 0], np.float32),
            1,
        )
        for index in np.flatnonzero(counts):
            first.setdefault(int(index), clock + 1)
    assert first == {0: 1, 1: 3, 2: 5}


def test_inhibitory_edge_does_not_become_an_excitatory_visual_pulse_result():
    ptr = np.array([0, 1, 1], dtype=np.int64)
    posts = np.array([1], dtype=np.int32)
    weights = signed_weights(ptr, np.array([200]), np.array([-1, 1]), 1.0)
    voltage, current = np.zeros(2, np.float32), np.zeros(2, np.float32)
    counts = advance(
        ptr,
        posts,
        weights,
        voltage,
        current,
        np.zeros(2, np.int16),
        np.zeros((3, 2), np.float32),
        0,
        np.array([200, 0], np.float32),
        8,
    )
    assert counts[0] > 0
    assert counts[1] == 0
    assert np.isfinite(voltage).all() and voltage[1] < 0


def test_unregistered_graph_cannot_be_labelled_as_full_malecns(tmp_path):
    (tmp_path / "manifest.json").write_text('{"neurons":166700}')
    with pytest.raises(ValueError, match="Unregistered"):
        load_registered_graph(tmp_path)
