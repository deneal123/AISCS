"""Experimental disk index of verified direct physical feedback events."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .direct_events import iter_direct_feedback
from .event_archive import iter_archived_edge_batches


def _ids_digest(ids):
    data = json.dumps(ids, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(data).hexdigest()


def build_direct_event_index(destination, archive_path, archive_sha256, graph, expected_ids, *,
                             duration_ms):
    """Stage, verify and atomically publish an index from one physical replay.

    This stores graph routing, not verified synaptic geometry or convergence.
    The original destination survives any parsing, verification or I/O error.
    """
    destination, archive_path = Path(destination), Path(archive_path)
    if destination.resolve() == archive_path.resolve():
        raise ValueError('Event archive and index must use different files')
    graph_hash = graph.provenance.get('manifest_sha256')
    if (not isinstance(graph_hash, str) or len(graph_hash) != 64
            or any(c not in '0123456789abcdef' for c in graph_hash)):
        raise ValueError('Invalid graph identity')
    fd, temporary = tempfile.mkstemp(prefix=f'.{destination.name}.', suffix='.tmp',
                                     dir=destination.parent)
    os.close(fd)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.execute('CREATE TABLE events (target INTEGER NOT NULL, source INTEGER NOT NULL, '
                           'tick INTEGER NOT NULL, count INTEGER NOT NULL, sign INTEGER NOT NULL, '
                           'PRIMARY KEY (target, source, tick)) WITHOUT ROWID')
        connection.execute('CREATE TABLE cells (id INTEGER PRIMARY KEY)')
        batches = iter_archived_edge_batches(archive_path, archive_sha256)
        count = 0
        for batch in iter_direct_feedback(graph, expected_ids, batches, duration_ms=duration_ms):
            connection.executemany('INSERT INTO events VALUES (?, ?, ?, ?, ?)',
                ((row['target_id'], row['source_id'], row['emission_tick_ms'],
                  row['synapse_count'], row['predicted_sign']) for row in batch))
            count += len(batch)
        connection.executemany('INSERT INTO cells VALUES (?)', ((body,) for body in expected_ids))
        info = {'version': '1', 'graph_sha256': graph_hash, 'archive_sha256': archive_sha256,
                'ids_sha256': _ids_digest(expected_ids), 'duration_ms': str(duration_ms),
                'event_count': str(count)}
        connection.executemany('INSERT INTO metadata VALUES (?, ?)', info.items())
        connection.commit()
        connection.close()
        connection = None
        with Path(temporary).open('rb') as stream:
            index_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        os.replace(temporary, destination)
        temporary = None
        return {**info, 'index_sha256': index_sha256}
    finally:
        if connection is not None:
            connection.close()
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_target_event_batches(path, targets, *, graph_sha256, archive_sha256, ids_sha256,
                              duration_ms):
    """Read target batches using one checked, read-only SQLite connection.

    Checks declared identities, not the cryptographic integrity of the index file.
    """
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return _read_target_event_batches(connection, targets, graph_sha256=graph_sha256,
            archive_sha256=archive_sha256, ids_sha256=ids_sha256, duration_ms=duration_ms)


def _read_target_event_batches(connection, targets, *, graph_sha256, archive_sha256, ids_sha256,
                               duration_ms):
    if (not isinstance(targets, (list, tuple)) or not targets or len(targets) > 4096
            or any(type(target) is not int or target <= 0 for target in targets)
            or len(set(targets)) != len(targets)
            or type(duration_ms) is not int or duration_ms < 1):
        raise ValueError('Invalid direct feedback target')
    info = dict(connection.execute('SELECT key, value FROM metadata'))
    if any(info.get(key) != value for key, value in {
                'version': '1', 'graph_sha256': graph_sha256, 'archive_sha256': archive_sha256,
                'ids_sha256': ids_sha256, 'duration_ms': str(duration_ms)}.items()):
        raise ValueError('Direct feedback index identity mismatch')
    result = {target: [] for target in targets}
    for start in range(0, len(targets), 500):
        group = targets[start:start + 500]
        marks = ','.join('?' for _ in group)
        present = {row[0] for row in connection.execute(
            f'SELECT id FROM cells WHERE id IN ({marks})', group)}
        if present != set(group):
            raise ValueError('Target is not in the indexed population')
        rows = connection.execute(
            f'SELECT target, source, tick, count, sign FROM events WHERE target IN ({marks}) '
            'ORDER BY target, source, tick', group)
        for target, source, tick, count, sign in rows:
            arrival = tick + 2
            result[target].append({'source_id': source, 'target_id': target,
                'emission_tick_ms': tick, 'delivery_tick_ms': arrival, 'synapse_count': count,
                'predicted_sign': sign, 'kind': 'physical-source-edge',
                'within_window': arrival <= duration_ms,
                'affects_replay': arrival < duration_ms})
    return result


def read_target_events(path, target, *, graph_sha256, archive_sha256, ids_sha256, duration_ms):
    """Read one target only after checking the index's declared identities."""
    return read_target_event_batches(path, [target], graph_sha256=graph_sha256,
        archive_sha256=archive_sha256, ids_sha256=ids_sha256, duration_ms=duration_ms)[target]


def read_verified_target_event_batches(path, targets, *, index_sha256, graph_sha256,
                                       archive_sha256, ids_sha256, duration_ms):
    """Check index bytes before and after a bounded lookup; never return altered data."""
    if (not isinstance(index_sha256, str) or len(index_sha256) != 64
            or any(char not in '0123456789abcdef' for char in index_sha256)):
        raise ValueError('Invalid direct feedback index digest')

    def check():
        with Path(path).open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == index_sha256

    if not check():
        raise ValueError('Direct feedback index digest mismatch')
    result = read_target_event_batches(path, targets, graph_sha256=graph_sha256,
        archive_sha256=archive_sha256, ids_sha256=ids_sha256, duration_ms=duration_ms)
    if not check():
        raise ValueError('Direct feedback index changed during lookup')
    return result


def iter_verified_target_event_batches(path, batches, *, index_sha256, graph_sha256,
                                       archive_sha256, ids_sha256, duration_ms):
    """Read a sequence of batches with one pair of hashes.

    Yielded batches are provisional: the consumer must stage them and publish
    only after exhausting this iterator successfully, including its final hash.
    """
    if (not isinstance(index_sha256, str) or len(index_sha256) != 64
            or any(char not in '0123456789abcdef' for char in index_sha256)):
        raise ValueError('Invalid direct feedback index digest')

    def check():
        with Path(path).open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == index_sha256

    if not check():
        raise ValueError('Direct feedback index digest mismatch')
    seen = set()
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        for targets in batches:
            values = _read_target_event_batches(connection, targets, graph_sha256=graph_sha256,
                archive_sha256=archive_sha256, ids_sha256=ids_sha256, duration_ms=duration_ms)
            if seen.intersection(values):
                raise ValueError('Repeated direct feedback target')
            seen.update(values)
            yield values
    if not check():
        raise ValueError('Direct feedback index changed during lookup')
