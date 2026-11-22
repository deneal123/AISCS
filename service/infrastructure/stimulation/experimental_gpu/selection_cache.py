"""The compartments a pass must record, resolved once per preparation identity.

The packer has to answer one question before it can hand a batch to the GPU:
which compartments of each cell must come back as traces. That answer is a
function of the cell's verified sources, the crossing threshold and the source
distance cut - none of which changes between passes - yet every pass recomputes
it after reading 187 KB of durable payload per cell.

Measured on the full population, that work is the largest single item charged to
the packer: 355 s of a 1010 s pass with the selection computed, 204 s with it
read, and 467 s when the packer does no durable work at all. The answer itself is
small - 17 736 664 compartments over 166 700 cells, 73.6 MB as int32 with a
64-bit offset per cell - and building it costs 154 s once.

Only the selection is cached. The candidate rows the archive records stay where
they were: a cell that reports no crossing emits no row, and only 3 of 166 700
report anything at all, so the rows of the quiet cells are withheld by
construction and their batches say so through the flags array.

The table is refused unless the identity that produced it matches: a different
preparation, threshold or distance cut makes every entry meaningless, and a
silently wrong selection would change the recording rather than the speed.
"""

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

FORMAT = 'malecns-output-selection-v1'
FORMAT_KEY = 'format'
_FILE = 'selection.npz'
_META = 'meta.json'
# One bit per cell: whether the cell owns at least one retained candidate. A
# quiet cell still has to tell the archive that its rows were withheld, and that
# is the only fact the renderer needs from a plan it will not otherwise use.
HAS_CANDIDATES = 1
# A cell also owns rows that survive regardless of whether a compartment crossed:
# an unresolved contact is a placeholder the archive records without ticks. Those
# cells need their real plan, so the flag names them instead of the pass guessing.
HAS_PLACEHOLDERS = 2
_DIGEST = re.compile('[0-9a-f]{64}')


def preparation_identity(metadata, params_identity):
    """Return a digest naming the prepared geometry a pass is about to solve.

    The selection depends on the reduced geometry of every cell, so it may only
    be reused against the same packed chunks and the same preparation parameters:
    a different parameter set moves the segment midpoints and every compartment
    index with them. The manifest digest itself is not carried in the metadata,
    but its chunk digests are, and together with the graph and source index
    digests they name the same snapshot.
    """
    chunks = metadata.get('chunks') if isinstance(metadata, dict) else None
    if (not isinstance(chunks, list) or not chunks
            or not all(isinstance(chunk, dict) and isinstance(chunk.get('sha256'), str)
                       for chunk in chunks)):
        raise ValueError('Invalid prepared geometry for the output selection')
    payload = {
        FORMAT_KEY: FORMAT,
        'params': list(params_identity),
        'chunks': [chunk['sha256'] for chunk in chunks],
        'graph_sha256': metadata.get('graph_sha256'),
        'source_index_sha256': metadata.get('source_index_sha256'),
        'vertices': metadata.get('vertices'),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def selection_identity(*, params_identity, threshold_mv, duration_ms, max_distance_um,
                       preparation_sha256):
    """Return the digest that names one selection table and nothing else."""
    if (not isinstance(params_identity, list)
            or not all(isinstance(value, (int, float, str)) for value in params_identity)
            or not isinstance(threshold_mv, (int, float)) or isinstance(threshold_mv, bool)
            or not isinstance(duration_ms, int) or isinstance(duration_ms, bool)
            or not (max_distance_um is None
                    or (isinstance(max_distance_um, (int, float))
                        and not isinstance(max_distance_um, bool)))
            or not isinstance(preparation_sha256, str)
            or not _DIGEST.fullmatch(preparation_sha256)):
        raise ValueError('Invalid output selection identity')
    payload = {
        FORMAT_KEY: FORMAT,
        'params': list(params_identity),
        'threshold_mv': float(threshold_mv),
        'duration_ms': int(duration_ms),
        'max_distance_um': None if max_distance_um is None else float(max_distance_um),
        'preparation_sha256': preparation_sha256,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


class SelectionCache:
    """Read or write one selection table under a directory named by its digest."""

    def __init__(self, directory, identity):
        if not isinstance(identity, str) or len(identity) != 64:
            raise ValueError('Invalid output selection directory identity')
        self.directory = Path(directory)
        self.identity = identity
        self.bodies = None
        self.offsets = None
        self.indices = None
        self.flags = None
        self._position = None

    def _entry(self):
        return self.directory / self.identity

    def load(self):
        """Return True when this identity's table is present and consistent."""
        entry = self._entry()
        meta = entry / _META
        data = entry / _FILE
        if not meta.is_file() or not data.is_file():
            return False
        try:
            with meta.open('rb') as handle:
                header = json.loads(handle.read().decode('ascii'))
            if (not isinstance(header, dict) or header.get(FORMAT_KEY) != FORMAT
                    or header.get('identity') != self.identity):
                return False
            expected = header.get('digest')
            with data.open('rb') as handle:
                if hashlib.sha256(handle.read()).hexdigest() != expected:
                    return False
            with np.load(data) as table:
                bodies = table['bodies'].copy()
                offsets = table['offsets'].copy()
                indices = table['indices'].copy()
                flags = table['flags'].copy()
        except Exception:
            return False
        if (bodies.ndim != 1 or bodies.dtype != np.int64 or offsets.ndim != 1
                or offsets.dtype != np.int64 or indices.ndim != 1
                or indices.dtype != np.int32 or flags.ndim != 1 or flags.dtype != np.uint8
                or len(offsets) != len(bodies) + 1 or len(flags) != len(bodies)
                or (len(offsets) and (offsets[0] != 0 or offsets[-1] != len(indices)))
                or (len(bodies) and (np.diff(offsets) < 0).any())):
            return False
        self.bodies, self.offsets, self.indices, self.flags = bodies, offsets, indices, flags
        self._position = {int(body): slot for slot, body in enumerate(bodies.tolist())}
        return True

    def entry_for(self, body):
        """Return (indices, flags) for one cell, or None when the cell is unlisted."""
        slot = self._position.get(body) if self._position is not None else None
        if slot is None:
            return None
        start, end = int(self.offsets[slot]), int(self.offsets[slot + 1])
        return self.indices[start:end].tolist(), int(self.flags[slot])

    def store(self, bodies, offsets, indices, flags):
        """Publish a table atomically; the metadata file is the commit point."""
        bodies = np.ascontiguousarray(bodies, dtype=np.int64)
        offsets = np.ascontiguousarray(offsets, dtype=np.int64)
        indices = np.ascontiguousarray(indices, dtype=np.int32)
        flags = np.ascontiguousarray(flags, dtype=np.uint8)
        if (len(offsets) != len(bodies) + 1 or len(flags) != len(bodies)
                or (len(offsets) and (offsets[0] != 0 or offsets[-1] != len(indices)))):
            raise ValueError('Invalid output selection table')
        entry = self._entry()
        entry.mkdir(parents=True, exist_ok=True)
        staging = entry / (_FILE + '.tmp')
        with staging.open('wb') as handle:
            np.savez(handle, bodies=bodies, offsets=offsets, indices=indices, flags=flags)
            handle.flush()
            os.fsync(handle.fileno())
        digest = hashlib.sha256(staging.read_bytes()).hexdigest()
        os.replace(staging, entry / _FILE)
        header = {FORMAT_KEY: FORMAT, 'identity': self.identity, 'digest': digest,
                  'cells': int(len(bodies)), 'compartments': int(len(indices))}
        temporary = entry / (_META + '.tmp')
        with temporary.open('wb') as handle:
            handle.write(json.dumps(header, sort_keys=True).encode('ascii'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, entry / _META)
        self.bodies, self.offsets, self.indices, self.flags = bodies, offsets, indices, flags
        self._position = {int(body): slot for slot, body in enumerate(bodies.tolist())}
        return header
