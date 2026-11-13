import hashlib
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from service.infrastructure.connectome.pair_cache import VerifiedSynapsePairs
from service.infrastructure.connectome.synapse_index import (
    PairQueryLimitExceeded,
    SynapseBatchIndex,
    build_batch_index,
)
from service.infrastructure.stimulation.feedback.observation_audit import (
    audit_feedback_observations,
)
from service.infrastructure.stimulation.population.pair_mapping import match_fragment_inputs_batch


@pytest.fixture
def indexed(tmp_path):
    source = tmp_path / 'source.arrow'
    table = pa.table({'body_pre': [10, 11], 'body_post': [20, 20],
                      **{name: [value, value] for name, value in {
                          'x_pre': 10, 'y_pre': 20, 'z_pre': 30,
                          'x_post': 100, 'y_post': 200, 'z_post': 300}.items()}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([10, 11, 20], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / 'index', digest)
    return SynapseBatchIndex(source, ids, tmp_path / 'index', digest), source, digest


def test_cache_bound_copy_identity_and_source_changes(indexed):
    index, source, digest = indexed
    rows = index.query(20, 'incoming', limit=None, partner_ids=[10])['pairs']
    cache = VerifiedSynapsePairs(index, max_rows=1)
    cache.remember(index, 10, 20, rows, digest)
    rows[0]['x_pre'] = -1
    assert cache.get(10, 20)[0]['x_pre'] == 10
    copy = cache.get(10, 20)
    copy[0]['x_pre'] = -2
    assert cache.get(10, 20)[0]['x_pre'] == 10
    with pytest.raises(ValueError, match='Conflicting'):
        cache.remember(index, 10, 20, copy, digest)
    other = index.query(20, 'incoming', limit=None, partner_ids=[11])['pairs']
    cache.remember(index, 11, 20, other, digest)
    assert cache.get(11, 20) is None
    with pytest.raises(ValueError, match='identity mismatch'):
        cache.verify(index, '0' * 32)
    with source.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='source changed'):
        cache.verify(index, digest)


def test_cache_rejects_changed_bitmap_and_different_index_instance(indexed):
    index, _source, digest = indexed
    cache = VerifiedSynapsePairs(index)
    replacement = SynapseBatchIndex(index.source_path, index.ids_path,
                                    index.bitmap_path.parent, digest)
    with pytest.raises(ValueError, match='identity mismatch'):
        cache.verify(replacement, digest)
    with index.bitmap_path.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='index changed'):
        cache.verify(index, digest)


def test_audit_reuses_verified_pair_and_queries_misses(indexed, monkeypatch):
    index, _source, digest = indexed
    rows = index.query(20, 'incoming', limit=None, partner_ids=[10])['pairs']
    cache = VerifiedSynapsePairs(index)
    cache.remember(index, 10, 20, rows, digest)
    module = 'service.infrastructure.stimulation.feedback.observation_audit.'
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'body_id': '20', 'sha256': 'a' * 64, 'swc': 'verified'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda _swc, points: {
        'child_node_ids': [7] * len(points), 'segment_fractions': [1.] * len(points),
        'centerline_distances_um': [.075] * len(points)})
    event = {'child_node_id': 7, 'position': 1.}
    origin = {'source_id': 10, 'source_tick_ms': 3, 'source_position_8nm': [10, 20, 30],
              'target_position_8nm': [100, 200, 300], 'target_distance_um': .075}
    schedule = {'events_by_target': {20: [event, event.copy()]},
                'provenance_by_target': {20: [origin, {**origin, 'source_id': 11}]},
                'target_morphology_sha256': {20: 'a' * 64}}
    expected = audit_feedback_observations(schedule, index, [], expected_source_md5=digest)
    calls = []
    original = index.query_exact_pairs

    def query(pairs, **kwargs):
        calls.append(pairs)
        return original(pairs, **kwargs)

    monkeypatch.setattr(index, 'query_exact_pairs', query)
    actual = audit_feedback_observations(schedule, index, [], expected_source_md5=digest,
                                         _pair_cache=cache)
    assert actual == expected and calls == [[(11, 20)]]
    bad = deepcopy(schedule)
    bad['provenance_by_target'][20][0]['source_position_8nm'][0] += 1
    with pytest.raises(ValueError, match='source-target observation'):
        audit_feedback_observations(bad, index, [], expected_source_md5=digest, _pair_cache=cache)
    monkeypatch.setattr(index, 'query_exact_pairs', lambda *_a, **_k: (_ for _ in ()).throw(
        PairQueryLimitExceeded('limited')))
    assert audit_feedback_observations(schedule, index, [], expected_source_md5=digest,
                                       _pair_cache=cache) == expected


def test_cached_audit_rejects_source_changed_during_projection(indexed, monkeypatch):
    index, source, digest = indexed
    rows = index.query(20, 'incoming', limit=None, partner_ids=[10])['pairs']
    cache = VerifiedSynapsePairs(index)
    cache.remember(index, 10, 20, rows, digest)

    def read_and_replace(*_args, **_kwargs):
        with source.open('ab') as stream:
            stream.write(b'changed')
        return {'body_id': '20', 'sha256': 'a' * 64, 'swc': 'verified'}

    module = 'service.infrastructure.stimulation.feedback.observation_audit.'
    monkeypatch.setattr(module + 'read_skeleton', read_and_replace)
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda _swc, points: {
        'child_node_ids': [7] * len(points), 'segment_fractions': [1.] * len(points),
        'centerline_distances_um': [.075] * len(points)})
    schedule = {'events_by_target': {20: [{'child_node_id': 7, 'position': 1.}]},
                'provenance_by_target': {20: [{
                    'source_id': 10, 'source_tick_ms': 3,
                    'source_position_8nm': [10, 20, 30],
                    'target_position_8nm': [100, 200, 300], 'target_distance_um': .075}]},
                'target_morphology_sha256': {20: 'a' * 64}}
    with pytest.raises(ValueError, match='source changed'):
        audit_feedback_observations(schedule, index, [], expected_source_md5=digest,
                                    _pair_cache=cache)


def test_exact_pair_query_matches_independent_queries_and_enforces_bound(indexed):
    index, source, _digest = indexed
    pairs = [(10, 20), (11, 20), (20, 10)]
    expected = {pair: index.query(pair[1], 'incoming', limit=None, partner_ids=[pair[0]])['pairs']
                for pair in pairs}
    assert index.query_exact_pairs(pairs) == expected
    with pytest.raises(PairQueryLimitExceeded):
        index.query_exact_pairs(pairs, max_rows=1)
    with pytest.raises(ValueError, match='Invalid exact'):
        index.query_exact_pairs([pairs[0], pairs[0]])
    with pytest.raises(ValueError, match='registered graph'):
        index.query_exact_pairs([(999, 20)])
    with source.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='source changed'):
        index.query_exact_pairs(pairs)


def test_multi_target_mapping_uses_exact_query_and_safe_fallback(indexed, monkeypatch):
    index, _source, digest = indexed
    pairs = [(10, 20), (11, 20)]
    diagnostics = {source: {'source_id': source, 'source_md5': digest, 'candidates': [{
        'included_in_graph': True, 'partner_id': '20', 'source_position_8nm': [10, 20, 30],
        'stimulated_ticks_ms': [1], 'centerline_distance_um': .1}]}
        for source, _target in pairs}
    graph = SimpleNamespace(posts=[0], provenance={'manifest_sha256': 'a' * 64})
    module = 'service.infrastructure.stimulation.population.pair_mapping.'
    monkeypatch.setattr(module + 'fragment_edge_schedule', lambda diag, **_k: {
        'source_id': diag['source_id'], 'graph_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'outgoing', lambda *_a: {
        'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 1}]})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a: {'swc': 'verified', 'sha256': 'b' * 64, 'body_id': '20'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9], 'segment_fractions': [.5], 'centerline_distances_um': [.1]})
    options = {'max_source_distance_um': 2, 'max_target_distance_um': 2, 'duration_ms': 3}
    cache = VerifiedSynapsePairs(index)
    accelerated = match_fragment_inputs_batch(pairs, diagnostics, index, graph, [],
                                               _pair_cache=cache, **options)
    assert cache.get(10, 20)[0]['x_post'] == 100
    monkeypatch.setattr(index, 'query_exact_pairs', lambda *_a, **_k: (_ for _ in ()).throw(
        PairQueryLimitExceeded('limited')))
    fallback = match_fragment_inputs_batch(pairs, diagnostics, index, graph, [], **options)
    assert accelerated == fallback


def test_exact_pairs_retain_batch_order_and_reject_cross_product(tmp_path):
    source = tmp_path / 'pairs.arrow'
    pres = [10, 10, 11, 10, 11]
    posts = [20, 21, 21, 20, 20]
    table = pa.table({'body_pre': pres, 'body_post': posts,
                      **{name: list(range(5)) for name in
                         ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=2)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([10, 11, 20, 21], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / 'index', digest)
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    pairs = [(10, 20), (11, 21)]
    result = index.query_exact_pairs(pairs)
    assert [row['x_pre'] for row in result[(10, 20)]] == [0, 3]
    assert [row['x_pre'] for row in result[(11, 21)]] == [2]
    for source_id, target_id in pairs:
        assert result[(source_id, target_id)] == index.query(
            target_id, 'incoming', limit=None, partner_ids=[source_id])['pairs']


def test_exact_pairs_reject_missing_coordinates(tmp_path):
    source = tmp_path / 'null.arrow'
    table = pa.table({'body_pre': [10], 'body_post': [20], 'x_pre': [None],
                      **{name: [1] for name in
                         ('y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([10, 20], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / 'index', digest)
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    with pytest.raises(ValueError, match='Invalid or missing'):
        index.query_exact_pairs([(10, 20)])


def test_audit_chunks_more_than_128_verified_pairs(tmp_path, monkeypatch):
    source = tmp_path / 'many.arrow'
    bodies = list(range(1, 131))
    table = pa.table({'body_pre': bodies, 'body_post': [500] * len(bodies),
                      **{name: [10] * len(bodies) for name in
                         ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=25)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([*bodies, 500], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / 'index', digest)
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    original = index.query_exact_pairs
    calls = []

    def exact(pairs, **kwargs):
        calls.append(len(pairs))
        return original(pairs, **kwargs)

    monkeypatch.setattr(index, 'query_exact_pairs', exact)
    module = 'service.infrastructure.stimulation.feedback.observation_audit.'
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'body_id': '500', 'sha256': 'a' * 64, 'swc': 'verified'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda _swc, points: {
        'child_node_ids': [7] * len(points), 'segment_fractions': [.5] * len(points),
        'centerline_distances_um': [.1] * len(points)})
    schedule = {'events_by_target': {500: [{'child_node_id': 7, 'position': .5}
                                          for _ in bodies]},
                'provenance_by_target': {500: [{
                    'source_id': body, 'source_tick_ms': 3,
                    'source_position_8nm': [10, 10, 10],
                    'target_position_8nm': [10, 10, 10], 'target_distance_um': .1}
                    for body in bodies]}, 'target_morphology_sha256': {500: 'a' * 64}}
    proof = audit_feedback_observations(schedule, index, [], expected_source_md5=digest)
    assert proof['verified_events'] == proof['verified_pairs'] == 130
    assert calls == [128, 2]

    module = 'service.infrastructure.stimulation.population.pair_mapping.'
    monkeypatch.setattr(module + 'match_fragment_inputs', lambda diagnostic, _index, _graph,
                        target, _dirs, **_kw: (diagnostic['source_id'], target))
    requested = [(body, 500) for body in reversed(bodies)]
    calls.clear()
    mapped = match_fragment_inputs_batch(
        requested, {body: {'source_id': body} for body in bodies}, index, object(), [])
    assert mapped == requested
    assert calls == [128, 2]
