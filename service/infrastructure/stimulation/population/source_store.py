"""Disk-backed source diagnostics shared by feedback replay passes.

The stored payload is the replay-independent cable mapping: it depends on the
graph, the synapse index, the packed morphology and the distance tolerance, and
never on the stimulus, the threshold or the duration. Those are stamped when the
diagnostics are read, so one database can serve several experiments and survive
between runs without changing a single measured distance.

Payloads are a small JSON header followed by one structured numpy array rather
than a JSON document: the population has 124 million registered contacts, which
JSON encodes at ~308 bytes each (~38 GB per tolerance) and numpy encodes at 48
bytes each (~6 GB). Both forms are digest-verified on read, so a truncated or
foreign database is still rejected.
"""

import hashlib
import json
import os
import sqlite3
import struct
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .source_geometry import source_cable_mapping

FORMAT = 'malecns-source-candidates-v2'
_CANDIDATE = np.dtype([('partner', '<i8'), ('position', '<i4', (3,)),
                       ('child', '<i4'), ('fraction', '<f8'), ('distance', '<f8'),
                       ('index', '<i4'), ('included', '<u1')])


def _encode(mapping):
    header = {key: value for key, value in mapping.items() if key != 'candidates'}
    rows = mapping['candidates']
    array = np.zeros(len(rows), dtype=_CANDIDATE)
    if rows:
        array['partner'] = np.fromiter((int(row['partner_id']) for row in rows),
                                       dtype='<i8', count=len(rows))
        array['position'] = np.fromiter(
            (value for row in rows for value in row['source_position_8nm']),
            dtype='<i4', count=3 * len(rows)).reshape(len(rows), 3)
        array['child'] = np.fromiter((int(row['child_node_id']) for row in rows),
                                     dtype='<i4', count=len(rows))
        array['fraction'] = np.fromiter((float(row['segment_fraction']) for row in rows),
                                        dtype='<f8', count=len(rows))
        array['distance'] = np.fromiter((float(row['centerline_distance_um']) for row in rows),
                                        dtype='<f8', count=len(rows))
        array['index'] = np.fromiter((int(row['result_segment_index']) for row in rows),
                                     dtype='<i4', count=len(rows))
        array['included'] = np.fromiter(
            (1 if row['included_in_graph'] is True else 0 for row in rows),
            dtype='<u1', count=len(rows))
    header['format'] = FORMAT
    header['rows'] = len(rows)
    head = json.dumps(header, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf8')
    return struct.pack('<I', len(head)) + head + array.tobytes()


def _counts(payload, max_distance_um):
    """Count registered contacts and those beyond the tolerance.

    The same payload already carries both numbers in its numpy body, so the
    count is vectorised field access instead of building one dictionary per
    contact: the population holds 124 million contacts and a per-row pass costs
    minutes where this costs seconds.
    """
    if len(payload) < 4:
        raise ValueError('Truncated source diagnostics payload')
    (size,) = struct.unpack('<I', payload[:4])
    body = payload[4 + size:]
    if len(body) % _CANDIDATE.itemsize:
        raise ValueError('Truncated source diagnostics payload')
    array = np.frombuffer(body, dtype=_CANDIDATE)
    registered = array['included'] == 1
    return (int(np.count_nonzero(registered)),
            int(np.count_nonzero(registered & (array['distance'] > max_distance_um))))


def _decode(payload, max_distance_um):
    if len(payload) < 4:
        raise ValueError('Truncated source diagnostics payload')
    (size,) = struct.unpack('<I', payload[:4])
    head = json.loads(payload[4:4 + size])
    if head.pop('format', None) != FORMAT or 'rows' not in head:
        raise ValueError('Unknown source diagnostics payload format')
    body = payload[4 + size:]
    rows = int(head.pop('rows'))
    if len(body) != rows * _CANDIDATE.itemsize:
        raise ValueError('Truncated source diagnostics payload')
    array = np.frombuffer(body, dtype=_CANDIDATE)
    # Field access on a structured array row costs microseconds per element, so
    # the whole column set is converted once and zipped. Measured on real cells:
    # 380 ms per cell row-by-row versus 6 ms this way, and the population has
    # 166 700 cells.
    partners = array['partner'].tolist()
    positions = array['position'].tolist()
    children = array['child'].tolist()
    fractions = array['fraction'].tolist()
    distances = array['distance'].tolist()
    indices = array['index'].tolist()
    included = array['included'].tolist()
    unresolved = 'geometry_unresolved'
    resolved = 'timing_or_trace_ambiguous'
    candidates = [
        {'included_in_graph': flag == 1, 'partner_id': str(partner),
         'source_position_8nm': position, 'child_node_id': child,
         'segment_fraction': fraction, 'centerline_distance_um': distance,
         'result_segment_index': index,
         'status': unresolved if distance > max_distance_um else resolved,
         'stimulated_ticks_ms': None, 'control_ticks_ms': None}
        for partner, position, child, fraction, distance, index, flag in
        zip(partners, positions, children, fractions, distances, indices, included)]
    return {**head, 'candidates': candidates}

class SourceDiagnosticsStore:
    """Stage authenticated source diagnostics, optionally across runs.

    Rows are keyed by the SHA-256 of the dataset identity, so one database can
    hold several graphs without mixing cells. Opening an existing complete
    database is supported; a truncated or foreign one is rejected on read.
    """

    def __init__(self, path, graph, index, *, threshold_mv, duration_ms,
                 simulation_sha256, max_distance_um, morphology_sha256, pairs=None):
        """Open the store; pairs optionally replaces the per-body source scan."""
        self.graph, self.index, self.pairs = graph, index, pairs
        self.graph_hash = graph.provenance['manifest_sha256']
        self.ids_hash = graph.provenance['array_sha256']['ids.npy']
        self.source_md5 = index.manifest['source_md5']
        if pairs is not None and (pairs.manifest.get('source_md5') != self.source_md5
                                  or pairs.manifest.get('ids_sha256') != self.ids_hash):
            raise ValueError('Source pair store does not match the synapse index')
        self.options = dict(threshold_mv=threshold_mv, duration_ms=duration_ms,
                            simulation_sha256=simulation_sha256,
                            max_distance_um=max_distance_um)
        self.hashes = morphology_sha256.copy()
        self.dataset = self._dataset_hash()
        self.lock = threading.RLock()
        # Several build shards may fill one database concurrently; the default
        # five-second busy timeout is far too short for that.
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=300.)
        self.db.execute('CREATE TABLE IF NOT EXISTS sources (dataset TEXT NOT NULL, '
                        'body INTEGER NOT NULL, digest TEXT NOT NULL, '
                        'payload BLOB NOT NULL, PRIMARY KEY (dataset, body))')
        # Derived counts, kept beside the payloads: the exclusion receipt of a
        # partial-geometry experiment is a property of the geometry, so it must
        # not depend on whether a pass was replayed or restored from the cache.
        self.db.execute('CREATE TABLE IF NOT EXISTS exclusions (dataset TEXT NOT NULL, '
                        'body INTEGER NOT NULL, registered INTEGER NOT NULL, '
                        'unresolved INTEGER NOT NULL, PRIMARY KEY (dataset, body))')
        # Reading a row is dominated by I/O: on a network or bind-mounted
        # filesystem one random 31 KB payload cost 4.5 ms, so the whole
        # population took ~750 s per pass while the GPU sat idle. Independent
        # read-only connections in a small pool measured 0.98 ms per cell at
        # eight threads on the same file and 0.24 ms on a local volume, so the
        # diagnostic read fans out instead of walking the batch serially.
        self.path = str(path)
        self.read_workers = max(1, min(16, int(os.environ.get(
            'GENERATOR_SOURCE_READ_WORKERS', '8') or 8)))
        self.readers = []
        self.reader_lock = threading.Lock()

    def _dataset_hash(self):
        payload = {'graph': self.graph_hash, 'ids': self.ids_hash,
                   'source_md5': self.source_md5,
                   'max_distance_um': self.options['max_distance_um']}
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                               allow_nan=False)
        return hashlib.sha256(canonical.encode('utf8')).hexdigest()

    def close(self):
        with self.lock:
            for reader in self.readers:
                reader.close()
            self.readers = []
            self.db.close()

    def _read_rows(self, bodies):
        """Read one shard of payloads over a private read-only connection."""
        reader = sqlite3.connect('file:' + self.path + '?mode=ro', uri=True, timeout=300.)
        decoded = {}
        try:
            for body in bodies:
                row = reader.execute(
                    'SELECT digest, payload FROM sources WHERE dataset = ? AND body = ?',
                    (self.dataset, body)).fetchone()
                if row is None or hashlib.sha256(row[1]).hexdigest() != row[0]:
                    raise ValueError('Missing or corrupted source diagnostics')
                decoded[body] = _decode(row[1], self.options['max_distance_um'])
        finally:
            reader.close()
        return decoded

    def _read_many(self, bodies):
        """Decode a batch of payloads, fanning the I/O out over threads.

        Order is irrelevant here because the caller re-keys the result by body
        id and every row is identity-checked afterwards.
        """
        if not bodies:
            return {}
        workers = min(self.read_workers, len(bodies))
        if workers < 2:
            return self._read_rows(bodies)
        shards = [bodies[index::workers] for index in range(workers)]
        decoded = {}
        with ThreadPoolExecutor(max_workers=workers,
                                 thread_name_prefix='source-diagnostics') as pool:
            for shard in pool.map(self._read_rows, shards):
                decoded.update(shard)
        return decoded

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _check_dataset(self):
        if (self.graph.provenance.get('manifest_sha256') != self.graph_hash
                or self.graph.provenance.get('array_sha256', {}).get('ids.npy') != self.ids_hash
                or self.index.manifest.get('source_md5') != self.source_md5
                or self.index.manifest.get('ids_sha256') != self.ids_hash):
            raise ValueError('Source diagnostics dataset identity changed')

    def covers(self):
        """Report whether every cell of this dataset is already staged.

        A restored replay pass performs no mapping, so the coupled iterations
        would then find no diagnostics for the cells that emitted events. Callers
        use this to refuse a cache hit until the database is complete.
        """
        with self.lock:
            (rows,) = self.db.execute('SELECT COUNT(*) FROM sources WHERE dataset = ?',
                                      (self.dataset,)).fetchone()
            return int(rows) == len(self.hashes)

    def cached_counts(self):
        """Return the staged contact counts, or None when they are incomplete.

        The counts are a property of the stored geometry, so they are cached
        beside the payloads rather than collected from whichever pass happened
        to decode a cell. A run restored entirely from the replay cache must
        still publish the same exclusion receipt as the run that computed it,
        and a partial table must not be mistaken for a complete one: an
        unfinished set would report fewer exclusions than the geometry holds.
        """
        with self.lock:
            known = self._known_counts()
            return None if len(known) != len(self.hashes) else known

    def remember_counts(self, counts):
        """Persist contact counts already derived by a caller's decoded batch."""
        if not counts:
            return
        with self.lock, self.db:
            self.db.executemany('INSERT OR IGNORE INTO exclusions VALUES (?, ?, ?, ?)',
                [(self.dataset, body, registered, unresolved)
                 for body, (registered, unresolved) in counts.items()])

    def fill_counts(self):
        """Derive the missing contact counts from the staged payloads.

        Reading every payload again costs one pass over the database, so this is
        only reached when a durable store predates the side table: afterwards the
        counts are cached and a warm repeat never pays for them.
        """
        with self.lock:
            known = self._known_counts()
            missing = [body for body in self.hashes if body not in known]
            if missing:
                workers = max(1, min(self.read_workers, len(missing)))
                shards = [missing[index::workers] for index in range(workers)]
                rows = {}
                with ThreadPoolExecutor(max_workers=workers,
                                         thread_name_prefix='source-exclusions') as pool:
                    for shard in pool.map(self._count_rows, shards):
                        rows.update(shard)
                self.remember_counts(rows)
                known.update(rows)
            return known

    def _known_counts(self):
        return {row[0]: (int(row[1]), int(row[2])) for row in self.db.execute(
            'SELECT body, registered, unresolved FROM exclusions WHERE dataset = ?',
            (self.dataset,))}

    def _count_rows(self, bodies):
        """Count one shard of payloads over a private read-only connection."""
        reader = sqlite3.connect('file:' + self.path + '?mode=ro', uri=True, timeout=300.)
        rows = {}
        try:
            for body in bodies:
                row = reader.execute(
                    'SELECT digest, payload FROM sources WHERE dataset = ? AND body = ?',
                    (self.dataset, body)).fetchone()
                if row is None or hashlib.sha256(row[1]).hexdigest() != row[0]:
                    raise ValueError('Missing or corrupted source diagnostics')
                rows[body] = _counts(row[1], self.options['max_distance_um'])
        finally:
            reader.close()
        return rows

    def diagnostics(self, bodies):
        with self.lock:
            return self._diagnostics(bodies)

    def _diagnostics(self, bodies, fresh=None):
        self._check_dataset()
        if (not isinstance(bodies, tuple) or not bodies or len(set(bodies)) != len(bodies)
                or any(type(body) is not int or body not in self.hashes for body in bodies)):
            raise ValueError('Invalid source diagnostics batch')
        # A cell mapped in this very call is already in memory: re-reading it
        # from disk and decoding it again costs about as much as the mapping
        # itself did, which is pure waste on a whole-population build.
        replayed = [body for body in bodies if fresh is None or body not in fresh]
        loaded = self._read_many(replayed)
        result = {}
        for body in bodies:
            data = fresh[body] if fresh is not None and body in fresh else loaded[body]
            if (data.get('body_id') != str(body)
                    or data.get('morphology_sha256') != self.hashes[body]
                    or data.get('graph_sha256') != self.graph_hash
                    or data.get('source_md5') != self.source_md5
                    or data.get('max_distance_um') != self.options['max_distance_um']):
                raise ValueError('Source diagnostics identity mismatch')
            result[body] = {**data, 'simulation_sha256': self.options['simulation_sha256'],
                            'duration_ms': self.options['duration_ms'],
                            'threshold_mv': float(self.options['threshold_mv'])}
        return result

    def metadata(self, cells):
        with self.lock:
            return self._metadata(cells)

    def _metadata(self, cells):
        from service.infrastructure.stimulation.experimental_gpu.grid_contract import (
            grid_configuration,
        )

        self._check_dataset()
        if (not isinstance(cells, list) or not cells
                or any(not isinstance(cell, dict) for cell in cells)):
            raise ValueError('Invalid prepared source batch')
        ids = [cell.get('id') for cell in cells]
        if (any(type(body) is not int or body not in self.hashes for body in ids)
                or len(set(ids)) != len(ids)
                or any(cell.get('morphology_sha256') != self.hashes[body]
                       for body, cell in zip(ids, cells, strict=True))):
            raise ValueError('Prepared source identity mismatch')
        # Mapping a whole chunk takes seconds; holding the write transaction for
        # that long serialises every other writer, which is why a sharded build
        # would otherwise run one shard at a time. Existence is therefore read
        # outside the transaction and the transaction covers only the inserts.
        # One statement per cell cost 0.2 ms of host time on the mounted
        # filesystem, which is 30 s per whole-population pass for nothing: the
        # existence test is a set membership answer, so it is asked in chunks.
        present = set()
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ','.join('?' * len(chunk))
            present.update(row[0] for row in self.db.execute(
                'SELECT body FROM sources WHERE dataset = ? AND body IN (' + placeholders + ')',
                (self.dataset, *chunk)))
        missing = [cell for body, cell in zip(ids, cells, strict=True) if body not in present]
        fresh = {}
        for cell in missing:
            fresh[cell['id']] = source_cable_mapping(cell, self.graph, self.index,
                max_distance_um=self.options['max_distance_um'], pairs=self.pairs)
        if fresh:
            rows = [(self.dataset, body, hashlib.sha256(payload).hexdigest(), payload)
                    for body, payload in ((body, _encode(mapping))
                                          for body, mapping in fresh.items())]
            with self.db:
                self.db.executemany('INSERT OR IGNORE INTO sources VALUES (?, ?, ?, ?)', rows)
        diagnostics = self._diagnostics(tuple(ids), fresh)
        provenance = {}
        for body, cell in zip(ids, cells, strict=True):
            receipt = {'body_id': str(body), 'morphology_sha256': self.hashes[body]}
            geometry = cell.get('geometry', {})
            if geometry.get('grid') is not None:
                receipt['configuration'] = grid_configuration(geometry['grid'],
                                                              geometry['edge_node_ids'])
            provenance[body] = receipt
        return {'diagnostics': diagnostics, 'provenance': {
            body: provenance[body] for body in ids}}
