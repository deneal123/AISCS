import numpy as np
import pytest

from service.infrastructure.connectome.neighbors import incoming, incoming_edge_indices_many
from tests.test_forced_network import graph


def test_batch_matches_individual_incoming_across_block_boundaries():
    fixture = graph()
    fixture.provenance['dataset_id'] = 'test'
    fixture.provenance['manifest_sha256'] = 'test'
    batches = incoming_edge_indices_many(fixture, [10, 20, 30], block_size=1)
    for body, indices in batches.items():
        page = incoming(fixture, body, 0, len(fixture.posts))
        source_indices = np.searchsorted(fixture.ptr, indices, side='right') - 1
        assert [str(int(fixture.ids[index])) for index in source_indices] == [
            row['source_id'] for row in page['items']]
        assert fixture.counts[indices].tolist() == [row['synapse_count'] for row in page['items']]


def test_batch_rejects_unknown_and_duplicate_targets():
    with pytest.raises(KeyError):
        incoming_edge_indices_many(graph(), [999])
    with pytest.raises(ValueError):
        incoming_edge_indices_many(graph(), [10, 10])
