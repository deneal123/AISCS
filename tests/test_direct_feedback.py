from types import SimpleNamespace

import numpy as np
import pytest

from service.application.feedback.direct_events import iter_direct_feedback
from service.infrastructure.connectome.source_feedback import suppressed_source_inputs


def graph():
    return SimpleNamespace(ids=np.array([10, 20, 30]), size=3,
        ptr=np.array([0, 2, 3, 3]), posts=np.array([0, 1, 0]),
        counts=np.array([1, 2, 3]), signs=np.array([1, -1, 1]),
        provenance={'manifest_sha256': 'a' * 64})


def test_direct_batches_match_existing_routing_including_self_edges():
    events = [{'source_id': 10, 'target_id': 10, 'tick': 1, 'count': 1},
              {'source_id': 10, 'target_id': 20, 'tick': 2, 'count': 2},
              {'source_id': 20, 'target_id': 10, 'tick': 4, 'count': 3}]
    batches = [{10: events[:2]}, {20: events[2:], 30: []}]
    result = [item for batch in iter_direct_feedback(graph(), [10, 20, 30], batches,
                                                      duration_ms=5) for item in batch]
    network = {'spike_neurons': np.array([], dtype=np.int32),
               'spike_times_ms': np.array([], dtype=np.int32)}
    expected = suppressed_source_inputs(graph(), [10, 20, 30], events, network,
                                        duration_ms=5)['events']
    def key(item):
        return (item['delivery_tick_ms'], item['source_id'], item['target_id'])
    assert sorted(result, key=key) == sorted(expected, key=key)
    assert result[-1]['within_window'] is False


def test_direct_stream_rejects_missing_repeated_and_invalid_sources():
    with pytest.raises(ValueError, match='Incomplete'):
        list(iter_direct_feedback(graph(), [10, 20], [{10: []}], duration_ms=5))
    with pytest.raises(ValueError, match='repeated'):
        list(iter_direct_feedback(graph(), [10, 20], [{10: []}, {10: []}], duration_ms=5))
    with pytest.raises(ValueError, match='Unknown'):
        list(iter_direct_feedback(graph(), [99], [], duration_ms=5))


@pytest.mark.parametrize('event, message', [
    ({'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 3}, 'exceeds'),
    ({'source_id': 10, 'target_id': 30, 'tick': 1, 'count': 1}, 'missing'),
    ({'source_id': 20, 'target_id': 10, 'tick': 1, 'count': 1}, 'Invalid'),
])
def test_direct_stream_rejects_invalid_graph_events(event, message):
    with pytest.raises(ValueError, match=message):
        list(iter_direct_feedback(graph(), [10, 20, 30],
                                  [{10: [event], 20: [], 30: []}], duration_ms=5))


def test_direct_stream_rejects_duplicate_edge_events():
    event = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}
    with pytest.raises(ValueError, match='Duplicate'):
        list(iter_direct_feedback(graph(), [10, 20], [{10: [event, event], 20: []}],
                                  duration_ms=5))


def test_direct_stream_rejects_duplicate_graph_edges():
    damaged = graph()
    damaged.posts = np.array([1, 1, 0])
    event = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}
    with pytest.raises(ValueError, match='ambiguous'):
        list(iter_direct_feedback(damaged, [10, 20], [{10: [event], 20: []}], duration_ms=5))
