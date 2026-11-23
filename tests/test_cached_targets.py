from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.population import cached_targets
from service.infrastructure.stimulation.population.cached_targets import (
    population_target_provider,
    prepare_cached_targets,
)


def entry(body):
    return {'skeleton': {'body_id': str(body), 'sha256': 'a' * 64},
            'geometry': (np.array([1, 2]), np.array([[0., 0., 0.], [1., 0., 0.]]),
                         np.array([-1, 0]), np.array([.1, .1]))}


class FakeSnapshot:
    """Authenticated-snapshot stand-in that yields chosen entries per chunk."""

    def __init__(self, chunks, *, fail=()):
        self.chunks = chunks
        self.fail = set(fail)
        self.reads = []

    def chunk_bodies(self, body):
        for bodies in self.chunks:
            if body in bodies:
                return list(bodies)
        return []

    def entries(self, selected_ids, *, workers=None):
        selection = set(selected_ids)
        self.reads.append(sorted(selection))
        for bodies in self.chunks:
            if selection.intersection(bodies):
                for body in bodies:
                    if body in selection:
                        yield entry(body)


def test_cached_target_provider_rejects_partial_snapshot(monkeypatch):
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'b' * 64})
    cache = {'directory': 'cache', 'expected_manifest_sha256': 'c' * 64,
             'source_index': 'index', 'source_audit': 'audit'}
    monkeypatch.setattr(cached_targets, '_open_snapshot',
                        lambda *args, **kwargs: FakeSnapshot([[10]]))
    with pytest.raises(ValueError, match='incomplete'):
        prepare_cached_targets(graph, [10, 20], geometry_cache=cache)
    monkeypatch.setattr(cached_targets, '_open_snapshot',
                        lambda *args, **kwargs: FakeSnapshot([[10, 20]]))
    provider = prepare_cached_targets(graph, [10, 20], geometry_cache=cache)
    assert provider(10)[0]['sha256'] == 'a' * 64
    with pytest.raises(ValueError, match='outside'):
        provider(30)


def test_derived_target_must_identify_source_and_derived_geometry(monkeypatch):
    graph = SimpleNamespace(ids=[842998], provenance={'manifest_sha256': 'b' * 64})
    cache = {'directory': 'cache', 'expected_manifest_sha256': 'c' * 64,
             'source_index': 'index', 'source_audit': 'audit'}
    monkeypatch.setattr(cached_targets, '_open_snapshot',
                        lambda *args, **kwargs: FakeSnapshot([[842998]]))
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
    """One chunk read per miss, and a bounded cache that re-reads after eviction."""
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'b' * 64})
    snapshot = FakeSnapshot([[10], [20]])
    monkeypatch.setattr(cached_targets, '_open_snapshot', lambda *a, **k: snapshot)
    provider = population_target_provider(graph, {10: 'a' * 64, 20: 'a' * 64},
                                          geometry_cache={}, cache_size=1)
    assert provider(10) == provider(10)
    provider(20)
    provider(10)
    assert snapshot.reads == [[10], [20], [10]]
    graph.provenance['manifest_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='identity'):
        provider(10)
    graph.provenance['manifest_sha256'] = 'b' * 64
    invalid = population_target_provider(graph, {10: 'f' * 64, 20: 'a' * 64}, geometry_cache={})
    with pytest.raises(ValueError, match='digest mismatch'):
        invalid(10)


def test_population_provider_prepares_the_whole_chunk_once(monkeypatch):
    """One read of a chunk serves every registered cell packed into it."""
    graph = SimpleNamespace(ids=[10, 20, 30], provenance={'manifest_sha256': 'b' * 64})
    snapshot = FakeSnapshot([[10, 20], [30]])
    monkeypatch.setattr(cached_targets, '_open_snapshot', lambda *a, **k: snapshot)
    provider = population_target_provider(graph, {body: 'a' * 64 for body in (10, 20, 30)},
                                          geometry_cache={}, cache_size=8)
    assert snapshot.reads == []
    provider(20)
    provider(10)
    provider(20)
    assert snapshot.reads == [[10, 20]]
    provider(30)
    assert snapshot.reads == [[10, 20], [30]]


def test_population_provider_does_not_fail_unrelated_requests_on_a_bad_neighbour(monkeypatch):
    """The known zero-edge cell must not poison its chunk neighbours."""
    graph = SimpleNamespace(ids=[10, 842998], provenance={'manifest_sha256': 'b' * 64})
    snapshot = FakeSnapshot([[10, 842998]])
    monkeypatch.setattr(cached_targets, '_open_snapshot', lambda *a, **k: snapshot)
    prepared = {'body_id': '10', 'sha256': 'a' * 64}
    original = cached_targets._prepare_entry

    def observe(entry, *, target_ids, derived_target):
        if int(entry['skeleton']['body_id']) == 842998:
            raise ValueError('Cached morphology contains zero-length segments')
        return 10, (prepared, 'geometry')

    monkeypatch.setattr(cached_targets, '_prepare_entry', observe)
    provider = population_target_provider(graph, {10: 'a' * 64, 842998: 'a' * 64},
                                          geometry_cache={}, cache_size=8)
    assert provider(10) == (prepared, 'geometry')
    with pytest.raises(ValueError, match='zero-length'):
        provider(842998)
    monkeypatch.setattr(cached_targets, '_prepare_entry', original)
