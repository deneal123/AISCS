import pytest

from service.infrastructure.stimulation.geometry_batching import batch_geometry


def item(identity, count):
    return {'id': identity, 'geometry': (range(count),)}


def test_batching_preserves_order_and_reuses_original_entries():
    entries = [item(i, count) for i, count in enumerate([2, 1, 4, 3, 1])]
    batches = list(batch_geometry([entries[:1], entries[1:3], entries[3:]],
                                  max_neurons=3, max_vertices=5))
    assert [[entry['id'] for entry in batch] for batch in batches] == [[0, 1], [2], [3, 4]]
    flattened = (entry for batch in batches for entry in batch)
    assert all(a is b for a, b in zip(entries, flattened, strict=True))


def test_batching_respects_cell_count_and_empty_chunks():
    entries = [item(i, 1) for i in range(5)]
    assert [len(group) for group in batch_geometry([[], entries, []], max_neurons=2)] == [2, 2, 1]
    assert list(batch_geometry([])) == []


@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_batching_rejects_invalid_limits(value):
    with pytest.raises(ValueError, match='bounds'):
        list(batch_geometry([], max_neurons=value))
    with pytest.raises(ValueError, match='bounds'):
        list(batch_geometry([], max_vertices=value))


def test_batching_rejects_oversized_and_malformed_entries():
    with pytest.raises(ValueError, match='bounds'):
        list(batch_geometry([[item(1, 6)]], max_vertices=5))
    with pytest.raises(ValueError, match='entry'):
        list(batch_geometry([[{}]]))
