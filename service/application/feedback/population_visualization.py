"""Export full-population candidate crossings for the existing scene protocol."""

import hashlib
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import numpy as np

from service.infrastructure.stimulation.population.source_events import HEADER

from .event_archive import iter_archived_source_batches


def export_population_markers(path, archive_path, archive_sha256, graph, *, duration_ms,
                              configuration_sha256):
    """Write SRC1 markers only after archive and complete population are verified.

    Markers denote candidate segment threshold crossings, not whole-cell spikes.
    The disk-backed ordering avoids holding all events in RAM. The caller must
    authenticate the graph and publish the containing result only on success.
    """
    destination = Path(path)
    graph_hash = graph.provenance.get('manifest_sha256')
    ids = np.asarray(graph.ids)
    if (destination.exists() or destination.is_symlink() or not destination.parent.is_dir()
            or ids.ndim != 1 or not len(ids) or len(ids) >= 2**32
            or ids.dtype.kind not in 'iu' or np.any(ids <= 0)
            or np.any(ids[1:] <= ids[:-1])
            or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                   for value in (graph_hash, configuration_sha256))
            or type(duration_ms) is not int or not 1 <= duration_ms <= 1000):
        raise ValueError('Invalid population marker identity')
    with tempfile.TemporaryDirectory(prefix='.population-markers-', dir=destination.parent) as tmp:
        scratch = Path(tmp)
        with closing(sqlite3.connect(scratch / 'markers.sqlite')) as db:
            db.execute('CREATE TABLE sources (position INTEGER PRIMARY KEY)')
            db.execute('CREATE TABLE events (tick INTEGER NOT NULL, position INTEGER NOT NULL, '
                       'PRIMARY KEY (tick, position)) WITHOUT ROWID')
            for batch in iter_archived_source_batches(archive_path, archive_sha256):
                positions = np.searchsorted(ids, list(batch))
                for (body, source), position in zip(batch.items(), positions, strict=True):
                    if position >= len(ids) or int(ids[position]) != body:
                        raise ValueError('Marker source is outside graph')
                    try:
                        db.execute('INSERT INTO sources VALUES (?)', (int(position),))
                    except sqlite3.IntegrityError as exc:
                        raise ValueError('Duplicate marker source') from exc
                    candidates = source.get('candidates')
                    if not isinstance(candidates, list):
                        raise ValueError('Missing marker candidates')
                    for candidate in candidates:
                        ticks = candidate.get('stimulated_ticks_ms') if isinstance(
                            candidate, dict) else None
                        if (not isinstance(ticks, list)
                                or any(type(tick) is not int or not 1 <= tick <= duration_ms
                                       for tick in ticks)
                                or ticks != sorted(set(ticks))):
                            raise ValueError('Invalid marker crossing ticks')
                        db.executemany('INSERT OR IGNORE INTO events VALUES (?, ?)',
                                       ((tick, int(position)) for tick in ticks))
            if db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] != len(ids):
                raise ValueError('Incomplete marker source population')
            count = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            if count >= 2**32 or count > len(ids) * duration_ms:
                raise ValueError('Population marker count exceeds format')
            staged = scratch / 'markers.bin'
            digest = hashlib.sha256()
            with staged.open('wb') as stream:
                header = HEADER.pack(b'SRC1', len(ids), duration_ms, count,
                                     bytes.fromhex(graph_hash), bytes.fromhex(configuration_sha256))
                stream.write(header)
                digest.update(header)
                for column in ('position', 'tick'):
                    cursor = db.execute(f'SELECT {column} FROM events ORDER BY tick, position')
                    while rows := cursor.fetchmany(65536):
                        data = np.asarray([row[0] for row in rows], dtype='<u4').tobytes()
                        stream.write(data)
                        digest.update(data)
            os.rename(staged, destination)
    return {'sha256': digest.hexdigest(), 'events': count, 'sources': len(ids),
            'interpretation': 'candidate segment crossings; not whole-cell spikes'}
