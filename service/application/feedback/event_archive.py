"""Atomic, bounded event archive for experimental population replay."""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path


class EventArchive:
    """Stage JSONL batches beside their destination until the replay succeeds.

    Each line is one event batch; JSON object keys are cell IDs as strings.
    The caller must validate the entire replay before calling ``commit``.
    """

    def __init__(self, destination):
        self.destination = Path(destination)
        self._file = None
        self._path = None
        self._committed = False
        self._digest = hashlib.sha256()

    def __enter__(self):
        fd, self._path = tempfile.mkstemp(
            prefix=f'.{self.destination.name}.', suffix='.tmp',
            dir=self.destination.parent,
        )
        self._file = os.fdopen(fd, 'w', encoding='utf-8', newline='\n')
        return self

    def write_batch(self, batch):
        if self._file is None or self._committed or not isinstance(batch, dict):
            raise ValueError('Invalid event archive state or batch')
        line = json.dumps(batch, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')) + '\n'
        self._file.write(line)
        self._digest.update(line.encode('utf-8'))

    @property
    def sha256(self):
        if not self._committed:
            raise ValueError('Event archive is not committed')
        return self._digest.hexdigest()

    def commit(self):
        if self._file is None or self._committed:
            raise ValueError('Invalid event archive state')
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._file = None
        os.replace(self._path, self.destination)
        self._path = None
        self._committed = True

    def __exit__(self, exc_type, exc, traceback):
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._path is not None:
            Path(self._path).unlink(missing_ok=True)
            self._path = None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate event archive key')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('Nonfinite event archive value')


def iter_archived_source_batches(path, expected_sha256):
    """Yield source diagnostics, checking digest and file identity at exhaustion.

    Yielded records must not be published until the iterator is fully consumed.
    Candidate coordinates are retained for subsequent geometry mapping.
    """
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(char not in '0123456789abcdef' for char in expected_sha256)):
        raise ValueError('Invalid event archive digest')
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        initial = os.fstat(stream.fileno())
        for line in stream:
            if not line.endswith(b'\n'):
                raise ValueError('Incomplete event archive line')
            digest.update(line)
            try:
                batch = json.loads(line, object_pairs_hook=_unique_object,
                                   parse_constant=_reject_constant)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError('Invalid event archive JSON') from exc
            if not isinstance(batch, dict) or not batch:
                raise ValueError('Invalid event archive batch')
            output = {}
            for key, value in batch.items():
                if (not key.isascii() or not key.isdigit() or key.startswith('0')
                        or not isinstance(value, dict)
                        or not isinstance(value.get('edge_events'), list)):
                    raise ValueError('Invalid event archive source')
                output[int(key)] = value
            yield output
        final = os.fstat(stream.fileno())
    if ((initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns,
         initial.st_ctime_ns) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns,
                                  final.st_ctime_ns) or digest.hexdigest() != expected_sha256):
        raise ValueError('Event archive changed or digest mismatch')


def iter_archived_edge_batches(path, expected_sha256):
    """Yield provisional edge events from a validated source archive."""
    for batch in iter_archived_source_batches(path, expected_sha256):
        yield {body: source['edge_events'] for body, source in batch.items()}


def iter_aligned_archive_batches(active_path, active_sha256, control_path, control_sha256, *,
                                 temporary_directory=None, check_cancelled=None):
    """Align independent archive batch layouts on disk; outputs are provisional.

    Both readers must be exhausted to validate their digests and population.
    The scratch index is deleted when the iterator closes, including on error.
    """
    if check_cancelled is not None and not callable(check_cancelled):
        raise ValueError('Invalid archive cancellation callback')
    with tempfile.TemporaryDirectory(dir=temporary_directory) as scratch:
        connection = sqlite3.connect(Path(scratch) / 'control.sqlite')
        try:
            connection.execute('CREATE TABLE control (id INTEGER PRIMARY KEY, '
                               'payload TEXT NOT NULL)')
            for batch in iter_archived_source_batches(control_path, control_sha256):
                if check_cancelled is not None:
                    check_cancelled()
                try:
                    connection.executemany('INSERT INTO control VALUES (?, ?)', (
                        (body, json.dumps(value, ensure_ascii=False, allow_nan=False,
                                          separators=(',', ':'))) for body, value in batch.items()))
                except sqlite3.IntegrityError as exc:
                    raise ValueError('Repeated control source') from exc
            connection.commit()
            for active in iter_archived_source_batches(active_path, active_sha256):
                if check_cancelled is not None:
                    check_cancelled()
                control = {}
                ids = list(active)
                for start in range(0, len(ids), 500):
                    group = ids[start:start + 500]
                    marks = ','.join('?' for _ in group)
                    found = dict(connection.execute(
                        f'SELECT id, payload FROM control WHERE id IN ({marks})', group))
                    if len(found) != len(group):
                        raise ValueError('Missing or repeated active source')
                    control.update((body, json.loads(found[body])) for body in group)
                    connection.executemany('DELETE FROM control WHERE id = ?',
                                           ((body,) for body in group))
                yield active, control
            if connection.execute('SELECT 1 FROM control LIMIT 1').fetchone() is not None:
                raise ValueError('Incomplete active source population')
        finally:
            connection.close()
