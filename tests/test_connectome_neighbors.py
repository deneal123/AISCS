from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.neighbors import incoming, outgoing


def graph():
    return SimpleNamespace(
        ids=np.array([101, 102, 9007199254740993], dtype=np.int64),
        ptr=np.array([0, 2, 2, 4]),
        posts=np.array([1, 2, 0, 1]),
        counts=np.array([3, 5, 7, 9]),
        signs=np.array([-1, 1, 0]),
        provenance={"dataset_id": "registered", "manifest_sha256": "source"},
    )


def test_pages_keep_exact_ids_counts_and_source_sign():
    first = outgoing(graph(), 101, 0, 1)
    assert first["total"] == 2 and first["next_offset"] == 1
    assert first["items"] == [{"target_id": "102", "synapse_count": 3, "model_sign": -1}]
    second = outgoing(graph(), 101, 1, 1)
    assert second["next_offset"] is None
    assert second["items"][0]["target_id"] == "9007199254740993"
    assert outgoing(graph(), 102, 0, 10)["items"] == []
    with pytest.raises(KeyError):
        outgoing(graph(), 103, 0, 10)


def test_incoming_pages_recover_actual_source_and_its_sign():
    first = incoming(graph(), 102, 0, 1)
    assert first["total"] == 2 and first["next_offset"] == 1
    assert first["items"] == [{"source_id": "101", "synapse_count": 3, "model_sign": -1}]
    second = incoming(graph(), 102, 1, 1)
    assert second["next_offset"] is None
    assert second["items"] == [
        {"source_id": "9007199254740993", "synapse_count": 9, "model_sign": 0}
    ]
    assert incoming(graph(), 102, 3, 1)["items"] == []
    with pytest.raises(KeyError):
        incoming(graph(), 103, 0, 10)
