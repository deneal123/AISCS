import hashlib

import pytest

from service.application.feedback.direct_event_index import (
    build_direct_event_index,
    iter_verified_target_event_batches,
    read_target_event_batches,
    read_target_events,
    read_verified_target_event_batches,
)
from service.application.feedback.event_archive import EventArchive
from tests.test_direct_feedback import graph


def create_archive(path):
    with EventArchive(path) as archive:
        archive.write_batch({10: {'edge_events': [
            {'source_id': 10, 'target_id': 10, 'tick': 1, 'count': 1},
            {'source_id': 10, 'target_id': 20, 'tick': 2, 'count': 2}]}})
        archive.write_batch({20: {'edge_events': []}, 30: {'edge_events': []}})
        archive.commit()
        return archive.sha256


def test_direct_index_routes_each_target_with_verified_identities(tmp_path):
    source, destination = tmp_path / 'events.jsonl', tmp_path / 'events.sqlite'
    digest = create_archive(source)
    info = build_direct_event_index(destination, source, digest, graph(), [10, 20, 30],
                                    duration_ms=5)
    kwargs = dict(graph_sha256='a' * 64, archive_sha256=digest,
                  ids_sha256=info['ids_sha256'], duration_ms=5)
    assert info['event_count'] == '2'
    assert read_target_events(destination, 10, **kwargs)[0]['source_id'] == 10
    events = read_target_events(destination, 20, **kwargs)
    assert len(events) == 1 and events[0]['delivery_tick_ms'] == 4
    assert read_target_events(destination, 30, **kwargs) == []
    batch = read_target_event_batches(destination, [30, 10, 20], **kwargs)
    assert list(batch) == [30, 10, 20]
    assert batch[30] == [] and batch[10][0]['target_id'] == 10
    assert batch[20] == events
    index_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert info['index_sha256'] == index_sha
    assert read_verified_target_event_batches(destination, [10, 20], index_sha256=index_sha,
                                              **kwargs)[20] == events
    with pytest.raises(ValueError, match='digest mismatch'):
        read_verified_target_event_batches(destination, [10], index_sha256='0' * 64, **kwargs)
    with pytest.raises(ValueError, match='Invalid direct feedback target'):
        read_target_event_batches(destination, [10, 10], **kwargs)
    with pytest.raises(ValueError, match='indexed population'):
        read_target_events(destination, 99, **kwargs)
    with pytest.raises(ValueError, match='identity mismatch'):
        read_target_events(destination, 20, **{**kwargs, 'archive_sha256': '0' * 64})


def test_direct_index_failure_preserves_prior_file(tmp_path):
    source, destination = tmp_path / 'events.jsonl', tmp_path / 'events.sqlite'
    digest = create_archive(source)
    destination.write_bytes(b'previous')
    with pytest.raises(ValueError, match='digest mismatch'):
        build_direct_event_index(destination, source, '0' * 64, graph(), [10, 20, 30],
                                 duration_ms=5)
    assert destination.read_bytes() == b'previous'
    assert set(tmp_path.iterdir()) == {source, destination}
    with pytest.raises(ValueError, match='different files'):
        build_direct_event_index(source, source, digest, graph(), [10, 20, 30], duration_ms=5)


def test_verified_lookup_rejects_index_changed_during_read(tmp_path, monkeypatch):
    from service.application.feedback import direct_event_index as module

    source, destination = tmp_path / 'events.jsonl', tmp_path / 'events.sqlite'
    digest = create_archive(source)
    info = build_direct_event_index(destination, source, digest, graph(), [10, 20, 30],
                                    duration_ms=5)
    index_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    original = module.read_target_event_batches

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        with destination.open('ab') as stream:
            stream.write(b'changed')
        return result

    monkeypatch.setattr(module, 'read_target_event_batches', change)
    with pytest.raises(ValueError, match='changed during lookup'):
        read_verified_target_event_batches(destination, [10], index_sha256=index_sha,
            graph_sha256='a' * 64, archive_sha256=digest, ids_sha256=info['ids_sha256'],
            duration_ms=5)


def test_streamed_lookup_is_provisional_until_final_digest(tmp_path):
    source, destination = tmp_path / 'events.jsonl', tmp_path / 'events.sqlite'
    digest = create_archive(source)
    info = build_direct_event_index(destination, source, digest, graph(), [10, 20, 30],
                                    duration_ms=5)
    kwargs = dict(index_sha256=info['index_sha256'], graph_sha256='a' * 64,
                  archive_sha256=digest, ids_sha256=info['ids_sha256'], duration_ms=5)
    result = list(iter_verified_target_event_batches(destination, [[10], [20, 30]], **kwargs))
    assert list(result[0]) == [10] and list(result[1]) == [20, 30]
    with pytest.raises(ValueError, match='Repeated'):
        list(iter_verified_target_event_batches(destination, [[10], [10]], **kwargs))
    stream = iter_verified_target_event_batches(destination, [[10], [20]], **kwargs)
    assert list(next(stream)) == [10]
    with destination.open('ab') as output:
        output.write(b'changed')
    with pytest.raises(ValueError, match='changed during lookup'):
        list(stream)


def test_streamed_lookup_reuses_connection_and_closes_on_early_stop(tmp_path, monkeypatch):
    from service.application.feedback import direct_event_index as module

    source, destination = tmp_path / 'events.jsonl', tmp_path / 'events.sqlite'
    digest = create_archive(source)
    info = build_direct_event_index(destination, source, digest, graph(), [10, 20, 30],
                                    duration_ms=5)
    original = module.sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        conn = original(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(module.sqlite3, 'connect', track)
    kwargs = dict(index_sha256=info['index_sha256'], graph_sha256='a' * 64,
                  archive_sha256=digest, ids_sha256=info['ids_sha256'], duration_ms=5)
    stream = iter_verified_target_event_batches(destination, [[10], [20], [30]], **kwargs)
    assert list(next(stream)) == [10]
    assert list(next(stream)) == [20]
    assert len(connections) == 1
    stream.close()
    with pytest.raises(module.sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')
