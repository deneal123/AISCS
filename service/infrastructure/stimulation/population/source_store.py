"""Temporary disk-backed source diagnostics shared by feedback replay passes."""

import hashlib
import json
import sqlite3
import threading

from .source_geometry import source_geometry_diagnostics


class SourceDiagnosticsStore:
    """Stage diagnostics from authenticated prepared cells for one calculation.

    The caller owns and deletes the scratch database, authenticates inputs and
    must not share the database with an untrusted writer.
    """

    def __init__(self, path, graph, index, *, threshold_mv, duration_ms,
                 simulation_sha256, max_distance_um, morphology_sha256):
        self.graph, self.index = graph, index
        self.graph_hash = graph.provenance['manifest_sha256']
        self.ids_hash = graph.provenance['array_sha256']['ids.npy']
        self.source_md5 = index.manifest['source_md5']
        self.options = dict(threshold_mv=threshold_mv, duration_ms=duration_ms,
                            simulation_sha256=simulation_sha256, max_distance_um=max_distance_um)
        self.hashes = morphology_sha256.copy()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE sources (body INTEGER PRIMARY KEY, '
                        'digest TEXT NOT NULL, payload BLOB NOT NULL)')

    def close(self):
        with self.lock:
            self.db.close()

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

    def diagnostics(self, bodies):
        with self.lock:
            return self._diagnostics(bodies)

    def _diagnostics(self, bodies):
        self._check_dataset()
        if (not isinstance(bodies, tuple) or not bodies or len(set(bodies)) != len(bodies)
                or any(type(body) is not int or body not in self.hashes for body in bodies)):
            raise ValueError('Invalid source diagnostics batch')
        result = {}
        for body in bodies:
            row = self.db.execute('SELECT digest, payload FROM sources WHERE body = ?',
                                  (body,)).fetchone()
            if row is None or hashlib.sha256(row[1]).hexdigest() != row[0]:
                raise ValueError('Missing or corrupted source diagnostics')
            data = json.loads(row[1])
            if (data.get('body_id') != str(body)
                    or data.get('morphology_sha256') != self.hashes[body]
                    or data.get('graph_sha256') != self.graph_hash
                    or data.get('source_md5') != self.source_md5
                    or data.get('simulation_sha256') != self.options['simulation_sha256']
                    or data.get('threshold_mv') != self.options['threshold_mv']
                    or data.get('duration_ms') != self.options['duration_ms']):
                raise ValueError('Source diagnostics identity mismatch')
            result[body] = data
        return result

    def metadata(self, cells):
        with self.lock:
            return self._metadata(cells)

    def _metadata(self, cells):
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
        with self.db:
            for body, cell in zip(ids, cells, strict=True):
                exists = self.db.execute('SELECT 1 FROM sources WHERE body = ?',
                                         (body,)).fetchone()
                if exists is None:
                    diagnostics = source_geometry_diagnostics(cell, self.graph, self.index,
                                                              **self.options)
                    payload = json.dumps(diagnostics, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode('utf8')
                    self.db.execute('INSERT INTO sources VALUES (?, ?, ?)',
                                    (body, hashlib.sha256(payload).hexdigest(), payload))
        diagnostics = self.diagnostics(tuple(ids))
        from service.infrastructure.stimulation.experimental_gpu.grid_contract import (
            grid_configuration,
        )

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
