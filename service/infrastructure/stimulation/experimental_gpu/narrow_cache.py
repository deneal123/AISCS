"""Durable cache of narrowed population cells.

A population pass decodes every morphology chunk and reduces every tree before
the solver ever sees a cell. Both steps are functions of the geometry and the
field configuration alone: neither the stimulus waveform nor the feedback
schedule reaches a narrowed cell. They are also the expensive half of the host
path - 530 s of decoding and 603 s of reduction in a full-population pass - and
they grow with morphology width, which is the order in which the population
arrives.

One entry stores the narrowed cells of one identity as a flat payload plus an
index of fixed-size records, grouped by the cache chunk each cell came from and
ordered by the visiting order of the run that built it. A cached pass walks the
groups in that same order, so it reproduces the same pool boundaries, the same
batches and therefore the same arithmetic as an uncached pass; it is a shorter
path to the same numbers, never a different computation.

The payload is COLUMNAR, not pickled. A narrowed cell is a fixed set of numeric
arrays, so the entry records that set once (the layout) and each cell carries
only the lengths of its arrays. Reading a cell is then a buffer offset and one
np.frombuffer per field. Pickling the same cells measured 23 ms per wide cell
to unpickle - 119 s to restore 5.46 GB against a disk that reads at 204 MB/s -
because pickle rebuilds every array through the object protocol. The flat form
costs one memcpy per array and no protocol at all.

Every record carries a digest of its own blob and the entry carries the exact
chunk and body inventory it was built from. A damaged, truncated or mismatched
entry must look like a miss, never like a measurement: silently replaying a
damaged geometry would change what the experiment computes.
"""

import hashlib
import json
import os
import re
import struct
from pathlib import Path

import numpy as np

FORMAT = 'malecns-narrow-cell-cache-v2'
_META = 'meta.json'
_INDEX = 'index.npy'
_PAYLOAD = 'payload.bin'
_DIGEST = 16
_RECORD = np.dtype([('body', '<i8'), ('group', '<i4'), ('offset', '<i8'),
                    ('length', '<i8'), ('digest', 'V16')])
_ALIGN = 8
# (owner, name, dtype, width). Width 0 is a scalar in the cell header, 1 is a
# vector whose length the cell stores, and 3/2 are (length, 3) and (length, 2).
_ARRAYS = (('geometry', 'parents', '<i8', 1),
           ('geometry', 'conductances', '<f8', 1),
           ('geometry', 'segment_nodes', '<i8', 1),
           ('geometry', 'area', '<f8', 1),
           ('geometry', 'starts_um', '<f8', 3),
           ('geometry', 'ends_um', '<f8', 3),
           ('geometry', 'midpoints_um', '<f8', 3),
           ('geometry', 'endpoint_radii_um', '<f8', 2),
           ('geometry', 'edge_node_ids', '<i8', 1),
           ('geometry', 'segment_index', '<i4', 1))
_CELL_ARRAYS = (('cell', 'field_current_na', '<f8', 1),
                ('cell', 'initial_gates', '<f8', 1))
# Keys a narrowed cell may carry without being part of the columnar layout.
# grid is materialised again from the layout when a batch actually needs it,
# events are attached per batch by the producer, and the morphology digest is
# stored as text.
_ABSENT = {'geometry.grid': None, 'cell.events': [], 'cell.morphology_sha256': None}
_TEXT = 'morphology_sha256'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _layout(recording):
    """The array layout of every cell in one entry, in payload order."""
    keys = list(_ARRAYS)
    if not recording:
        keys = [key for key in keys if key[1] not in
                ('starts_um', 'ends_um', 'midpoints_um', 'endpoint_radii_um',
                 'edge_node_ids', 'segment_index')]
    keys.extend(_CELL_ARRAYS)
    return [[owner, name, dtype, width] for owner, name, dtype, width in keys]


def bodies_digest(bodies):
    """Digest of a body inventory, order-independent."""
    return hashlib.sha256(','.join(str(int(body)) for body in sorted(bodies))
                          .encode('utf8')).hexdigest()


def params_identity(params):
    """Every physical input of preparation, in a stable order."""
    identity = []
    for name in ('source_um', 'return_um', 'current_na', 'conductivity_s_m',
                 'clearance_um', 'axial_resistivity', 'capacitance', 'nseg'):
        value = getattr(params, name)
        # The probe points are the only vector-valued inputs; flattening keeps
        # them comparable instead of relying on tuple identity.
        if isinstance(value, (tuple, list)):
            identity.extend(float(item) for item in value)
        else:
            identity.append(float(value))
    return identity


def inventory(metadata, order, limit=None):
    """Chunk count and body digest of the chunks a request will visit."""
    chunks = metadata['chunks']
    positions = list(range(len(chunks))) if order is None else list(order)
    if limit is not None:
        positions = positions[:limit]
    bodies = []
    for position in positions:
        bodies.extend(int(item['body_id']) for item in chunks[position]['neurons'])
    return len(positions), bodies_digest(bodies)


def cache_key(*, geometry_sha256, source_index_sha256, params, recording, events, reroot):
    """Hash every input that can change a narrowed cell."""
    if (not isinstance(geometry_sha256, str) or not re.fullmatch('[a-f0-9]{64}', geometry_sha256)
            or not isinstance(source_index_sha256, str)
            or not re.fullmatch('[a-f0-9]{64}', source_index_sha256)):
        raise ValueError('Invalid narrow-cache identity')
    payload = {'format': FORMAT, 'geometry_sha256': geometry_sha256,
               'source_index_sha256': source_index_sha256,
               'params': params_identity(params),
               'recording': bool(recording), 'events': bool(events),
               'reroot': bool(reroot)}
    return hashlib.sha256(_canonical(payload).encode('utf8')).hexdigest()


def geometry_digest(metadata):
    """Digest of the geometry manifest a pass is about to read."""
    payload = dict(metadata)
    payload['directory'] = str(metadata['directory'])
    return hashlib.sha256(_canonical(payload).encode('utf8')).hexdigest()


def _digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _align(size):
    return size + (-size % _ALIGN)


def encode_cell(cell, layout):
    """Flatten one narrowed cell into a self-describing byte blob."""
    parts = []
    lengths = []
    for owner, name, dtype, width in layout:
        value = (cell if owner == 'cell' else cell['geometry'])[name]
        array = np.ascontiguousarray(value, dtype=np.dtype(dtype))
        shape = (array.shape[0],) if width == 1 else (array.shape[0], width)
        if array.ndim != len(shape) or array.shape != shape:
            raise NarrowCacheError('Narrowed-cell array has an unexpected shape')
        lengths.append(int(array.shape[0]))
        block = array.tobytes()
        # Every array starts on an 8-byte boundary so the reader can point
        # np.frombuffer straight at the mapping without realigning copies.
        parts.append(block + b'\0' * (_align(len(block)) - len(block)))
    text = cell.get(_TEXT)
    text = b'' if text is None else str(text).encode('utf8')
    head = struct.pack('<dI', float(cell['initial_voltage_mv']), len(text)) + text
    head += b'\0' * (_align(len(head)) - len(head))
    sizes = b''.join(struct.pack('<q', length) for length in lengths)
    return b''.join([head, sizes, *parts])


def decode_cell(blob, layout, *, body=None):
    """Rebuild one narrowed cell from its blob without touching pickle."""
    (voltage, text_length) = struct.unpack_from('<dI', blob, 0)
    cursor = 12
    text = bytes(blob[cursor:cursor + text_length]).decode('utf8') if text_length else None
    cursor = _align(cursor + text_length)
    lengths = struct.unpack_from('<' + 'q' * len(layout), blob, cursor)
    cursor = _align(cursor + 8 * len(layout))
    geometry = {}
    cell = {'field_current_na': None, 'initial_gates': None}
    for (owner, name, dtype, width), length in zip(layout, lengths, strict=True):
        if width == 0:
            continue
        count = int(length) * (width if width > 1 else 1)
        size = count * np.dtype(dtype).itemsize
        array = np.frombuffer(blob, dtype=np.dtype(dtype), count=count,
                              offset=cursor).reshape((length,) if width == 1 else (length, width))
        cursor = _align(cursor + size)
        (geometry if owner == 'geometry' else cell)[name] = array.copy()
    cell['initial_voltage_mv'] = float(voltage)
    if text is not None:
        cell[_TEXT] = text
    cell['id'] = body
    cell['events'] = _ABSENT['cell.events']
    geometry['grid'] = _ABSENT['geometry.grid']
    cell['geometry'] = geometry
    return cell


class NarrowCellStore:
    """Read-only view of one committed entry; groups replay in build order."""

    __slots__ = ('_meta', '_header', '_file', '_groups', '_layout', '_spans',
                 '_prefetch', '_prefetched', '_inflight')

    def __init__(self, meta, header, handle):
        self._meta = meta
        self._header = header
        self._file = handle
        self._layout = [tuple(entry) for entry in meta['layout']]
        groups = {}
        for position, row in enumerate(header):
            groups.setdefault(int(row['group']), []).append(position)
        self._groups = groups
        # The writer appends one chunk's cells in one run, so a group is a
        # contiguous span of the payload: read it with one syscall instead of
        # one per record.
        spans = {}
        for number, positions in groups.items():
            first = int(header[positions[0]]['offset'])
            last = header[positions[-1]]
            spans[number] = (first, int(last['offset']) + int(last['length']))
        self._spans = spans
        self._prefetch = None
        self._prefetched = {}
        self._inflight = {}

    @property
    def key(self):
        return self._meta['key']

    @property
    def cells(self):
        return int(self._meta['cells'])

    @property
    def groups(self):
        return len(self._groups)

    @property
    def payload_bytes(self):
        return int(self._meta['payload_bytes'])

    def _fetch(self, number):
        start, end = self._spans[number]
        window = os.pread(self._file.fileno(), end - start, start)
        if len(window) != end - start:
            raise NarrowCacheError('Narrowed-cell cache payload is truncated')
        return (start, window)

    def preload(self, numbers):
        """Read groups ahead of the decode; measured slower than plain pread.

        Kept for callers that want the option, but iter_cached_batches does not
        use it: on the widest 80 chunks this path measured 173.71 s against
        131.05 s for reading each group as it is consumed, because the extra
        resident windows cost more memory traffic than the overlap saves.
        """
        pending = [number for number in numbers
                   if number not in self._prefetched and number not in self._inflight]
        if not pending:
            return
        if self._prefetch is None:
            from concurrent.futures import ThreadPoolExecutor
            self._prefetch = ThreadPoolExecutor(max_workers=1,
                                                thread_name_prefix='narrow-read')
        # Submit and return: waiting here would make the read synchronous again.
        for number in pending:
            self._inflight[number] = self._prefetch.submit(self._fetch, number)

    def group(self, number):
        """Rebuild one chunk group, verifying every record digest.

        The whole group is fetched with one pread: the read runs without the GIL,
        so the packer thread keeps decoding the next chunk while this one streams
        off disk. A posix read of a page-faulting mmap would instead hold the GIL
        for every fault, which measured 28 MB/s inside a live pass against
        86 MB/s standalone.
        """
        fetched = self._prefetched.pop(number, None)
        if fetched is None:
            future = self._inflight.pop(number, None)
            fetched = future.result() if future is not None else self._fetch(number)
        start, window = fetched
        cells = []
        for position in self._groups[number]:
            row = self._header[position]
            base = int(row['offset']) - start
            blob = window[base:base + int(row['length'])]
            if hashlib.sha256(blob).digest()[:_DIGEST] != bytes(row['digest']):
                raise NarrowCacheError('Narrowed-cell cache record is corrupted')
            cells.append(decode_cell(blob, self._layout, body=int(row['body'])))
        return cells

    def close(self):
        if self._prefetch is not None:
            self._prefetch.shutdown(wait=True)
            self._prefetch = None
        self._prefetched.clear()
        self._inflight.clear()
        self._file.close()


class NarrowCacheError(ValueError):
    """A cache entry that exists but cannot be used."""


class NarrowCellWriter:
    """Stream narrowed cells to a scratch entry and publish it atomically."""

    __slots__ = ('_entry', '_key', '_meta', '_payload', '_rows', '_bodies',
                 '_layout', 'committed')

    def __init__(self, entry, key, meta):
        entry.mkdir(parents=True, exist_ok=True)
        self._entry = entry
        self._key = key
        self._meta = dict(meta)
        self._layout = _layout(bool(meta.get('recording')))
        self._payload = (entry / _PAYLOAD).open('wb')
        self._rows = []
        self._bodies = []
        self.committed = False

    def add(self, group, cell):
        if cell.get('events'):
            # Events belong to a batch, not to a geometry: an entry that
            # replayed them would replay one pass's schedule into another.
            raise NarrowCacheError('A narrowed cell carries events the cache cannot store')
        if cell.get('geometry', {}).get('grid') is not None:
            raise NarrowCacheError('A narrowed cell carries an explicit grid the cache cannot store')
        blob = encode_cell(cell, self._layout)
        self._rows.append((int(cell['id']), int(group), self._payload.tell(), len(blob),
                           hashlib.sha256(blob).digest()[:_DIGEST]))
        self._bodies.append(int(cell['id']))
        self._payload.write(blob)

    def commit(self):
        """Publish the entry; the metadata file is written last."""
        chunks = len({int(row[1]) for row in self._rows})
        self._payload.flush()
        os.fsync(self._payload.fileno())
        self._payload.close()
        if not self._rows:
            raise NarrowCacheError('Refusing to publish an empty narrowed-cell cache')
        header = np.zeros(len(self._rows), dtype=_RECORD)
        for position, row in enumerate(self._rows):
            header[position] = row
        np.save(self._entry / _INDEX, header, allow_pickle=False)
        meta = dict(self._meta, format=FORMAT, key=self._key, cells=len(self._rows),
                    chunks=int(chunks), layout=[list(entry) for entry in self._layout],
                    payload_bytes=os.path.getsize(self._entry / _PAYLOAD),
                    index_sha256=_digest_file(self._entry / _INDEX),
                    bodies_sha256=bodies_digest(self._bodies))
        # The metadata file is the commit point: an entry without it, or with a
        # stale one, is a miss even when its payload looks complete.
        scratch = self._entry / (_META + '.tmp')
        scratch.write_text(_canonical(meta), encoding='utf8')
        os.replace(scratch, self._entry / _META)
        self.committed = True
        return meta

    def discard(self):
        self._payload.close()


class NarrowCellCache:
    """Locate, open and build narrowed-cell entries under one directory."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def entry(self, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('Invalid narrow-cache key')
        return self.directory / key[:2] / key

    def open(self, key, *, chunks, bodies):
        """Return a verified store for exactly this inventory, or None on a miss."""
        entry = self.entry(key)
        meta_path = entry / _META
        try:
            if (not meta_path.is_file() or not (entry / _INDEX).is_file()
                    or not (entry / _PAYLOAD).is_file()):
                return None
            meta = json.loads(meta_path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            return None
        if (not isinstance(meta, dict) or meta.get('format') != FORMAT
                or meta.get('key') != key
                or type(meta.get('cells')) is not int or meta['cells'] < 1
                or type(meta.get('chunks')) is not int or meta['chunks'] != int(chunks)
                or meta.get('bodies_sha256') != bodies
                or type(meta.get('payload_bytes')) is not int
                or meta['payload_bytes'] != os.path.getsize(entry / _PAYLOAD)
                or meta.get('index_sha256') != _digest_file(entry / _INDEX)
                or not isinstance(meta.get('layout'), list) or not meta['layout']):
            return None
        header = np.load(entry / _INDEX, allow_pickle=False)
        if (header.dtype != _RECORD or header.shape != (meta['cells'],)
                or int(header['length'].sum()) != meta['payload_bytes']
                or len(set(header['group'].tolist())) != meta['chunks']):
            return None
        try:
            handle = (entry / _PAYLOAD).open('rb', buffering=0)
        except OSError:
            return None
        return NarrowCellStore(meta, header, handle)

    def writer(self, key, meta):
        return NarrowCellWriter(self.entry(key), key, meta)
