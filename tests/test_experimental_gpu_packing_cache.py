import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.packing_cache import PackedTreeCache


def test_cache_reuses_exact_geometry_and_rejects_mutation():
    cache = PackedTreeCache(100000)
    parent = np.array([-1, 0], dtype=np.int64)
    trees = [(parent, np.array([0., 1.]), np.array([1]))]
    first = cache.get_or_pack(trees)
    assert cache.get_or_pack(trees) is first
    with pytest.raises(ValueError):
        first.parents[0, 0] = 5
    parent[1] = 1
    with pytest.raises(ValueError):
        cache.get_or_pack(trees)


def test_cache_budget_can_disable_storage():
    cache = PackedTreeCache(0)
    trees = [([-1, 0], [0., 1.], [1])]
    assert cache.get_or_pack(trees) is not cache.get_or_pack(trees)
    assert cache.bytes == 0
