"""Flat on-disk cache of narrowed cells for the wide tail of the population.

Why this exists
---------------
A recorded pass narrows every cell (prepare + reduce) and then immediately
hands it to the solver. The narrowing is a pure function of the cell's geometry
and of the preparation parameters, so it is identical in every pass of an
experiment. On the measured population it costs 1010 s of a 1028 s pass, while
the GPU is idle 90 % of the time: the host producer is the critical path.

An earlier attempt cached pickled cells and lost (1.03x) because it wrote 38 GB
and paid a per-record SHA-256 plus pickle parsing on the way back. A narrowed
cell is a fixed set of numpy arrays, so a chunk can be stored as one contiguous
blob with an offset table and read back with numpy.frombuffer: no pickle, one
pread per chunk, one digest per chunk instead of per cell.

Selection
---------
Only the wide tail is cached. A widened cell costs ~77 bytes per segment, so at
the measured widths the cells above 10 000 segments are 1.2 MB each and the
whole tail is a few GB, which fits on disk; the narrow head is cheaper to
recompute than to read. The threshold is a property of the cache, not of the
caller: the builder and the reader are handed the same number.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

FORMAT = 'malecns-flat-narrow-cache-v1'

# The arrays a narrowed cell carries when it is recorded: the geometry the
# cell-major kernels read plus the bounds and identifiers the recorder needs.
GEOMETRY_KEYS = ('parents', 'conductances', 'segment_nodes', 'area', 'grid',
                 'starts_um', 'ends_um', 'midpoints_um', 'endpoint_radii_um',
                 'edge_node_ids', 'segment_index')
CELL_KEYS = ('id', 'field_current_na', 'initial_voltage_mv', 'initial_gates',
             'morphology_sha256')
_SCALARS = ('id', 'initial_voltage_mv', 'morphology_sha256')


def _encoded(cell):
    """Yield (key, dtype string, shape, raw bytes) for every stored array."""
    for key in GEOMETRY_KEYS:
        value = cell['geometry'].get(key)
        if value is None:
            yield key, '', (), b''
            continue
        array = np.ascontiguousarray(value)
        yield key, array.dtype.str, array.shape, array.tobytes()
    for key in CELL_KEYS:
        value = cell.get(key)
        if value is None or key in _SCALARS:
            yield key, '', (), b''
            continue
        array = np.ascontiguousarray(value)
        yield key, array.dtype.str, array.shape, array.tobytes()


class FlatNarrowCache:
    """One directory of chunk blobs plus a manifest that names their identity."""

    def __init__(self, directory, *, threshold):
        if type(threshold) is not int or threshold < 0:
            raise ValueError('Invalid wide-cell threshold')
        self.directory = Path(directory)
        self.threshold = threshold
        # A fresh instance is a reader until the caller says it is building. The
        # two roles must never mix inside one pass: a writer that also served
        # chunks would answer itself with cells it has just produced.
        self.writing = False
        self._meta = None
        self._written = {'chunks': 0, 'cells': 0, 'bytes': 0}
        self._read = {'chunks': 0, 'cells': 0, 'bytes': 0, 'hits': 0, 'misses': 0}
        self._pending = []
        self._manifest_path = self.directory / 'manifest.json'

    # -- identity ---------------------------------------------------------

    def identity(self):
        return {'format': FORMAT, 'threshold': self.threshold,
                'geometry_keys': list(GEOMETRY_KEYS), 'cell_keys': list(CELL_KEYS)}

    def compatible(self, metadata, manifest_sha256=None):
        """Is the manifest on disk an entry for this exact inventory?

        The geometry manifest does not carry its own digest (it is what the
        digest authenticates), so the caller that verified it must pass the
        expected value. A cache entry built for another snapshot would otherwise
        be indistinguishable from a valid one.
        """
        try:
            with self._manifest_path.open('r', encoding='utf-8') as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(meta, dict) or meta.get('identity') != self.identity():
            return None
        if (meta.get('graph_sha256') != metadata.get('graph_sha256')
                or meta.get('source_index_sha256') != metadata.get('source_index_sha256')
                or meta.get('manifest_sha256')
                != (manifest_sha256 or metadata.get('sha256'))):
            return None
        # A pass that found its entry is a reader for the rest of its life; without
        # this the instance would keep writing blobs next to the ones it reads.
        self.writing = False
        self._meta = meta
        return meta

    # -- writing ----------------------------------------------------------

    def begin_build(self):
        """Switch this instance to the writing role for one pass."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.writing = True
        self._written = {'chunks': 0, 'cells': 0, 'bytes': 0}

    def wants(self, cell):
        return len(cell['geometry']['edge_node_ids']) >= self.threshold

    def add(self, id, cell):
        """Keep one narrowed cell in memory until the chunk is flushed."""
        self._pending.append((id, cell))

    def begin(self):
        self._pending = []

    def flush(self, position):
        """Write the pending cells of one source chunk as a single blob."""
        if not self._pending:
            return
        entries = []
        blobs = []
        cursor = 0
        for body, cell in self._pending:
            start = cursor
            layout = []
            for key, dtype, shape, raw in _encoded(cell):
                layout.append((key, dtype, list(shape)))
                blobs.append(raw)
                cursor += len(raw)
            # Scalars travel in the JSON header: they are a few bytes each and do
            # not deserve a blob slot, but they are load-bearing. morphology_sha256
            # is the identity the durable store checks every cell against.
            scalars = {}
            for key in _SCALARS:
                value = cell.get(key)
                if isinstance(value, np.generic):
                    value = value.item()
                scalars[key] = value
            entries.append({'id': body, 'start': start, 'end': cursor, 'layout': layout,
                            'scalars': scalars})
        digest = hashlib.sha256()
        for raw in blobs:
            digest.update(raw)
        path = self.directory / (chunk_name(position) + '.bin')
        header = json.dumps({'format': FORMAT, 'entries': entries,
                             'payload': cursor, 'sha256': digest.hexdigest()}).encode('utf-8')
        with path.open('wb') as handle:
            handle.write(len(header).to_bytes(8, 'little'))
            handle.write(header)
            for raw in blobs:
                handle.write(raw)
        self._written['chunks'] += 1
        self._written['cells'] += len(entries)
        self._written['bytes'] += cursor
        self._pending = []

    def commit(self, metadata, manifest_sha256=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        meta = {'format': FORMAT, 'identity': self.identity(),
                'graph_sha256': metadata.get('graph_sha256'),
                'source_index_sha256': metadata.get('source_index_sha256'),
                'manifest_sha256': manifest_sha256 or metadata.get('sha256'),
                'written': dict(self._written), 'cells': self._written['cells']}
        staged = self._manifest_path.with_suffix('.json.staged')
        with staged.open('w', encoding='utf-8') as handle:
            json.dump(meta, handle, sort_keys=True)
        os.replace(staged, self._manifest_path)
        self._meta = meta
        return meta

    # -- reading ----------------------------------------------------------

    def covers(self, positions):
        """Are all the blobs this scope needs actually on disk?"""
        if self._meta is None:
            return False
        return all((self.directory / (chunk_name(position) + '.bin')).is_file()
                   for position in positions)

    def has(self, position):
        return (self._meta is not None
                and (self.directory / (chunk_name(position) + '.bin')).is_file())

    def load(self, position):
        """Return the narrowed cells of one chunk, or None when it is absent."""
        if self._meta is None:
            return None
        path = self.directory / (chunk_name(position) + '.bin')
        try:
            blob = path.read_bytes()
        except OSError:
            self._read['misses'] += 1
            return None
        try:
            header_bytes = int.from_bytes(blob[:8], 'little')
            header = json.loads(blob[8:8 + header_bytes].decode('utf-8'))
            entries = header['entries']
        except (ValueError, KeyError, UnicodeDecodeError):
            return None
        body = 8 + header_bytes
        expected = header.get('sha256')
        if (hashlib.sha256(blob[body:body + header.get('payload', 0)]).hexdigest()
                != expected):
            # A truncated or overwritten chunk must be a miss, never a silent
            # substitute: the cells it holds are geometry the solver trusts.
            self._read['misses'] += 1
            return None
        cells = {}
        for entry in entries:
            position = body + entry['start']
            geometry = {}
            cell = {'events': []}
            for key, dtype, shape in entry['layout']:
                if not dtype:
                    # Only a scalar or the grid sentinel reaches this branch; a
                    # narrowed cell carries grid as None.
                    if key in GEOMETRY_KEYS:
                        geometry[key] = None
                    elif key == 'id':
                        cell[key] = entry['id']
                    else:
                        cell[key] = None
                    continue
                dtype = np.dtype(dtype)
                count = int(np.prod(shape)) if shape else 1
                array = np.frombuffer(blob, dtype=dtype, count=count, offset=position)
                if shape:
                    array = array.reshape(shape)
                position += array.nbytes
                if key in GEOMETRY_KEYS:
                    geometry[key] = array
                else:
                    cell[key] = array if shape else array[0]
            for key, value in (entry.get('scalars') or {}).items():
                cell[key] = value
            cell['geometry'] = geometry
            cells[entry['id']] = cell
        self._read['chunks'] += 1
        self._read['hits'] += 1
        self._read['cells'] += len(cells)
        self._read['bytes'] += header.get('payload', 0)
        return cells

    def receipt(self):
        return {'format': FORMAT, 'threshold': self.threshold,
                'manifest': self._meta is not None,
                'written': dict(self._written), 'read': dict(self._read)}


def chunk_name(position):
    """The blob name of one cache chunk.

    Chunks are identified by their position in the visiting order of the pass
    that built the entry, not by the geometry chunk name: the narrowed cells are
    the same whichever descriptor they came from, and the visiting order is what
    both the builder and the reader derive from the manifest.
    """
    if type(position) is not int or position < 0:
        raise ValueError('Invalid geometry chunk position')
    return 'c%06d' % position


def digest_of(metadata):
    """The inventory identity a cache entry is valid for."""
    return {'graph_sha256': metadata.get('graph_sha256'),
            'source_index_sha256': metadata.get('source_index_sha256'),
            'manifest_sha256': metadata.get('sha256')}