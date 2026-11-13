import hashlib
import json
import os
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from service.infrastructure.connectome.synapse_index import (
    SynapseBatchIndex,
    build_batch_index,
    registered_page_pairs,
)
from service.infrastructure.connectome.synapse_morphology import (
    merge_candidate_pages,
    registered_incoming_candidates_single_pass,
    registered_page_candidates,
)
from service.infrastructure.connectome.synapse_pairs import extract_pairs
from tests.test_synapse_morphology import SWC


def test_cached_query_rejects_replaced_source_with_original_size_and_mtime(tmp_path):
    source = tmp_path / "source.arrow"
    table = pa.table({"body_pre": [1], "body_post": [2], **{
        key: [10] for key in ("x_pre", "y_pre", "z_pre", "x_post", "y_post", "z_post")
    }})
    with pa.OSFile(str(source), "wb") as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / "ids.npy"
    np.save(ids, np.array([1, 2], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / "index", digest)
    index = SynapseBatchIndex(source, ids, tmp_path / "index", digest)
    assert index.query(1, "outgoing")["total"] == 1
    original = source.stat()
    replacement = tmp_path / "replacement.arrow"
    content = bytearray(source.read_bytes())
    content[len(content) // 2] ^= 1
    replacement.write_bytes(content)
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, source)
    assert source.stat().st_size == original.st_size
    assert source.stat().st_mtime_ns == original.st_mtime_ns
    with pytest.raises(ValueError, match="source changed"):
        index.query(1, "outgoing")


def test_repository_rechecks_cached_index_and_manifest(tmp_path, monkeypatch):
    from service.infrastructure.connectome import synapse_repository

    source = tmp_path / 'source.arrow'
    table = pa.table({'body_pre': [1], 'body_post': [2], **{
        key: [10] for key in ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([1, 2], dtype=np.int64))
    build_batch_index(source, ids, tmp_path / 'index-v1', digest)
    monkeypatch.setattr(synapse_repository, 'SOURCE_NAME', source.name)
    monkeypatch.setattr(synapse_repository, 'SOURCE_MD5', digest)
    synapse_repository._open_index.cache_clear()
    try:
        first = synapse_repository.registered_index(tmp_path, ids)
        assert synapse_repository.registered_index(tmp_path, ids) is first
        manifest = tmp_path / 'index-v1' / 'manifest.json'
        replacement = tmp_path / 'replacement.json'
        replacement.write_bytes(manifest.read_bytes())
        os.replace(replacement, manifest)
        with pytest.raises(ValueError, match='index changed'):
            synapse_repository.registered_index(tmp_path, ids)
    finally:
        synapse_repository._open_index.cache_clear()


def test_index_directions_batches_and_integrity(tmp_path, monkeypatch):
    source = tmp_path / 'source.arrow'
    table = pa.table({'body_pre': [1, 2, 1, 9], 'body_post': [2, 1, 9, 1],
                      **{key: [10, 11, 12, 13] for key in
                         ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=2)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([1, 2], dtype=np.int64))
    result = build_batch_index(source, ids, tmp_path / 'index', digest)
    bits = np.load(tmp_path / 'index' / 'batches.npy')
    assert bits.shape == (2, 2, 1)
    assert bits[:, :, 0].tolist() == [[3, 1], [3, 1]]
    assert result == json.loads((tmp_path / 'index' / 'manifest.json').read_text())
    actual = hashlib.sha256((tmp_path / 'index' / 'batches.npy').read_bytes()).hexdigest()
    assert result['bitmap_sha256'] == actual
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    for direction in ('incoming', 'outgoing'):
        assert index.query(1, direction, limit=1) == extract_pairs(
            source, 1, digest, direction=direction, limit=1
        )
    graph = SimpleNamespace(ids=np.array([1, 2]), ptr=np.array([0, 1, 2]),
                            posts=np.array([1, 0]), counts=np.array([1, 1]),
                            signs=np.array([1, -1]), provenance={
                                'array_sha256': {'ids.npy': result['ids_sha256']},
                                'dataset_id': 'test', 'manifest_sha256': 'test-hash'})
    for direction in ('incoming', 'outgoing'):
        page = registered_page_pairs(index, graph, 1, direction, 0, 20)
        assert page['total'] == 1 and page['counts_match']
        assert page['edge_counts'][0]['partner_id'] == '2'
        page['pairs'][0]['x_pre'] = -999
        assert registered_page_pairs(index, graph, 1, direction, 0, 20)['pairs'][0]['x_pre'] != -999
    monkeypatch.setattr('service.infrastructure.connectome.morphology_repository.read_skeleton',
                        lambda *_args: {'body_id': '1', 'sha256': 'f' * 64, 'swc': SWC})
    expected = merge_candidate_pages([registered_page_candidates(
        index, graph, 1, 'incoming', 0, 20, [], candidate_partner_ids={2})])
    actual = registered_incoming_candidates_single_pass(
        index, graph, 1, [], candidate_partner_ids={2})
    assert actual == expected
    no_events = registered_incoming_candidates_single_pass(
        index, graph, 1, [], candidate_partner_ids=set())
    assert no_events['candidates'] == [] and no_events['complete_graph_edge_coverage']
    graph.counts[1] = 2
    with pytest.raises(ValueError, match='inconsistent'):
        registered_incoming_candidates_single_pass(index, graph, 1, [], candidate_partner_ids=set())
    graph.counts[1] = 1
    graph.counts[0] = 2
    assert not registered_page_pairs(index, graph, 1, 'outgoing', 0, 20)['counts_match']
    with pytest.raises(ValueError, match='Partner'):
        index.query(1, 'incoming', partner_ids=[9])
    with pytest.raises(ValueError, match='registered'):
        index.query(9, 'incoming')
    with pytest.raises(FileExistsError):
        build_batch_index(source, ids, tmp_path / 'index', digest)
    with pytest.raises(ValueError, match='checksum'):
        build_batch_index(source, ids, tmp_path / 'bad', '0' * 32)
    assert not (tmp_path / 'bad').exists()
    with (tmp_path / 'index' / 'batches.npy').open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='index changed'):
        index.query(1, 'incoming')
    with source.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='source changed'):
        index.query(1, 'incoming')
    with pytest.raises(ValueError, match='integrity'):
        SynapseBatchIndex(source, ids, tmp_path / 'index', digest)


def test_index_rejects_unordered_ids(tmp_path):
    source = tmp_path / 'source.arrow'
    source.write_bytes(b'data')
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([2, 1]))
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    with pytest.raises(ValueError, match='sorted'):
        build_batch_index(source, ids, tmp_path / 'index', digest)


def test_full_page_preserves_more_than_ten_thousand_source_pairs(tmp_path):
    count = 10001
    source = tmp_path / 'source.arrow'
    table = pa.table({'body_pre': [1] * count, 'body_post': [2] * count,
                      **{key: [10] * count for key in
                         ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=3000)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([1, 2], dtype=np.int64))
    manifest = build_batch_index(source, ids, tmp_path / 'index', digest)
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    graph = SimpleNamespace(ids=np.array([1, 2]), ptr=np.array([0, 1, 1]),
                            posts=np.array([1]), counts=np.array([count]), signs=np.array([1]),
                            provenance={'array_sha256': {'ids.npy': manifest['ids_sha256']},
                                        'dataset_id': 'test', 'manifest_sha256': 'test-hash'})
    bounded = registered_page_pairs(index, graph, 1, 'outgoing', 0, 20)
    complete = registered_page_pairs(index, graph, 1, 'outgoing', 0, 20, all_pairs=True)
    assert bounded['truncated'] and bounded['returned'] == 10000
    assert complete['counts_match'] and not complete['truncated']
    assert complete['returned'] == count


def test_single_pass_matches_interleaved_multi_page_sources(tmp_path, monkeypatch):
    partners = list(range(1, 26))
    source = tmp_path / 'source.arrow'
    order = list(reversed(partners))
    table = pa.table({'body_pre': order, 'body_post': [99] * len(order),
                      **{key: list(range(1, len(order) + 1)) for key in
                         ('x_pre', 'y_pre', 'z_pre', 'x_post', 'y_post', 'z_post')}})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=4)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([*partners, 99]))
    manifest = build_batch_index(source, ids, tmp_path / 'index', digest)
    index = SynapseBatchIndex(source, ids, tmp_path / 'index', digest)
    graph = SimpleNamespace(ids=np.array([*partners, 99]), ptr=np.array([*range(26), 25]),
                            posts=np.full(25, 25), counts=np.ones(25, dtype=int),
                            signs=np.ones(26, dtype=int), provenance={
                                'array_sha256': {'ids.npy': manifest['ids_sha256']},
                                'dataset_id': 'test', 'manifest_sha256': 'graph'})
    monkeypatch.setattr('service.infrastructure.connectome.morphology_repository.read_skeleton',
                        lambda *_args: {'body_id': '99', 'sha256': 'f' * 64, 'swc': SWC})
    selected = {1, 4, 20, 21, 25}
    pages = [registered_page_candidates(index, graph, 99, 'incoming', offset, 20, [],
                                        candidate_partner_ids=selected) for offset in (0, 20)]
    expected = merge_candidate_pages(pages)
    actual = registered_incoming_candidates_single_pass(
        index, graph, 99, [], candidate_partner_ids=selected)
    assert actual == expected
    assert [item['partner_id'] for item in actual['candidates']] == ['20', '4', '1', '25', '21']
