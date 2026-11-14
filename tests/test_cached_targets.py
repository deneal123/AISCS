from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.population.cached_targets import (
    population_target_provider,
    prepare_cached_targets,
)


def entry(body):
    return {'skeleton': {'body_id': str(body), 'sha256': 'a' * 64},
            'geometry': (np.array([1, 2]), np.array([[0., 0., 0.], [1., 0., 0.]]),
                         np.array([-1, 0]), np.array([.1, .1]))}


def test_cached_target_provider_rejects_partial_snapshot(monkeypatch):
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'b' * 64})
    cache = {'directory': 'cache', 'expected_manifest_sha256': 'c' * 64,
             'source_index': 'index', 'source_audit': 'audit'}
    module = 'service.infrastructure.stimulation.population.cached_targets.'
    monkeypatch.setattr(module + 'iter_selected_cache', lambda *args, **kwargs: iter([entry(10)]))
    with pytest.raises(ValueError, match='incomplete'):
        prepare_cached_targets(graph, [10, 20], geometry_cache=cache)
    monkeypatch.setattr(module + 'iter_selected_cache',
                        lambda *args, **kwargs: iter([entry(10), entry(20)]))
    provider = prepare_cached_targets(graph, [10, 20], geometry_cache=cache)
    assert provider(10)[0]['sha256'] == 'a' * 64
    with pytest.raises(ValueError, match='outside'):
        provider(30)


def test_derived_target_must_identify_source_and_derived_geometry(monkeypatch):
    graph = SimpleNamespace(ids=[842998], provenance={'manifest_sha256': 'b' * 64})
    cache = {'directory': 'cache', 'expected_manifest_sha256': 'c' * 64,
             'source_index': 'index', 'source_audit': 'audit'}
    module = 'service.infrastructure.stimulation.population.cached_targets.'
    monkeypatch.setattr(module + 'iter_selected_cache',
                        lambda *args, **kwargs: iter([entry(842998)]))
    receipt = {'source_sha256': 'a' * 64, 'derived_sha256': 'd' * 64}
    derived = {'body_id': '842998', 'sha256': 'd' * 64, 'transformation': receipt}
    provider = prepare_cached_targets(graph, [842998], geometry_cache=cache,
                                      derived_target=lambda _: (derived, 'geometry'))
    assert provider(842998) == (derived, 'geometry')
    receipt['source_sha256'] = 'e' * 64
    with pytest.raises(ValueError, match='provenance'):
        prepare_cached_targets(graph, [842998], geometry_cache=cache,
                               derived_target=lambda _: (derived, 'geometry'))


def test_population_target_provider_checks_hash_and_bounds_cache(monkeypatch):
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'b' * 64})
    calls = []

    def prepare(_graph, ids, **_kwargs):
        calls.append(ids[0])
        return lambda body: ({'body_id': str(body), 'sha256': 'a' * 64}, 'geometry')

    monkeypatch.setattr('service.infrastructure.stimulation.population.cached_targets.'
                        'prepare_cached_targets', prepare)
    provider = population_target_provider(graph, {10: 'a' * 64, 20: 'a' * 64},
                                          geometry_cache={}, cache_size=1)
    assert provider(10) == provider(10)
    provider(20)
    provider(10)
    assert calls == [10, 20, 10]
    graph.provenance['manifest_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='identity'):
        provider(10)
    graph.provenance['manifest_sha256'] = 'b' * 64
    invalid = population_target_provider(graph, {10: 'f' * 64, 20: 'a' * 64}, geometry_cache={})
    with pytest.raises(ValueError, match='digest mismatch'):
        invalid(10)
