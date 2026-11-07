import numpy as np
import pytest

from service.application.feedback.cell_solution_cache import CellSolutionCache, _size


def test_keys_include_every_numerical_input():
    key = CellSolutionCache.key
    base = (10, 'a' * 64, {'dt_ms': .025}, [{'time': 1}], {'nseg': 3})
    assert key(*base) == key(*base)
    for changed in ((11, *base[1:]), (10, 'b' * 64, *base[2:]),
                    (10, base[1], {'dt_ms': .05}, *base[3:]),
                    (*base[:3], [{'time': 2}], base[4]),
                    (*base[:4], {'nseg': 5})):
        assert key(*changed) != key(*base)
    with pytest.raises(ValueError):
        key(10, base[1], {'dt_ms': float('nan')}, [], {})


def test_bounded_lru_and_defensive_copies():
    value = {'x': np.array([1., 2.])}
    cache = CellSolutionCache(_size(value))
    cache.put('first', value)
    value['x'][0] = 99.
    hit = cache.get('first')
    assert hit['x'][0] == 1.
    hit['x'][1] = 99.
    assert cache.get('first')['x'][1] == 2.
    cache.put('second', {'x': np.array([3., 4.])})
    assert cache.get('first') is None
    assert cache.get('second')['x'][0] == 3.
    cache.put('oversized', np.ones(100))
    assert cache.get('oversized') is None and cache.bytes <= cache.max_bytes


def test_stable_policy_avoids_full_scan_thrashing_and_replaces_changed_cell():
    cache = CellSolutionCache(4 * _size(np.array([1.])), policy='stable')
    for cell in range(1, 5):
        cache.put(f'{cell}-a', np.array([cell], dtype=np.float64), group=cell)
    # All four fit; a new group is not admitted when the cache is full.
    cache.put('5-a', np.array([5.]), group=5)
    assert cache.get('1-a') is not None and cache.get('5-a') is None
    cache.put('1-b', np.array([9.]), group=1)
    assert cache.get('1-a') is None and cache.get('1-b')[0] == 9.
    assert cache.bytes <= cache.max_bytes
    with pytest.raises(ValueError, match='cell ID'):
        cache.put('invalid', np.array([1.]))
