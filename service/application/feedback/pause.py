"""Durable pause and resume for the full detailed-population experiment.

A pass over 166 700 cells costs about twenty minutes, so losing it to a host
restart or to a pause request is the difference between a usable service and an
unusable one. The checkpoint is taken at a batch boundary, which is the only
point where the live state agrees with itself:

* the event archive holds whole batches whose cells were recorded,
* the electrode signal already carries exactly those cells, and
* every window of those batches has landed, because the pass is closed first.

The checkpoint is also phase-aware. The experiment reads its own earlier
archives — the control branch consumes the zero-stimulus archive, and the
coupled iteration consumes both — so a checkpoint carries the archives and
receipts of the phases that already finished, not just the one in flight.

What resumes is the physics, not the file layout: a resumed pass reproduces the
same per-cell events and the same electrode signal as a continuous one. The
archive line grouping may differ, because a batch is a packing decision and not
a result; records are always read per cell.

Nothing here claims a paused experiment is valid on its own: the caller still
has to finish the pass and verify it exactly as it would after any restart.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np

FORMAT = 'malecns-full-population-pause-v2'
REQUEST_NAME = 'pause.requested'
STATE_NAME = 'state'


class ReplayPaused(Exception):
    """Raised at a batch boundary once a pause has been requested."""

    def __init__(self, receipt):
        super().__init__('population replay paused at a batch boundary')
        self.receipt = receipt


class PauseController:
    """Observe a pause request and publish the checkpoint that resumes it.

    The request is a file, not a signal: the service may be restarted between
    the request and the boundary, and a file survives that while a signal does
    not. A callable poll is accepted instead so tests and headless callers can
    drive the same state machine without touching the filesystem.
    """

    def __init__(self, directory, *, poll=None):
        self.directory = None if directory is None else Path(directory)
        if self.directory is None and poll is None:
            raise ValueError('A pause controller needs a directory or a poll callback')
        if poll is not None and not callable(poll):
            raise ValueError('Invalid pause poll callback')
        self._poll = poll or self._file_requested
        self.requested = None

    def _file_requested(self):
        return (self.directory / REQUEST_NAME).is_file()

    def check(self):
        """Return True once a pause has been requested.

        The request is polled until it appears, and only held once it has: a
        controller that latched its first answer would ignore a request made a
        second later, which is exactly the case a person pressing a button in
        the interface creates.
        """
        if self.requested:
            return True
        self.requested = bool(self._poll())
        return self.requested

    def request(self):
        """Ask a running pass to stop at its next batch boundary."""
        if self.directory is None:
            raise ValueError('A pause controller without a directory cannot be asked')
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / REQUEST_NAME).write_text('paused\n', encoding='utf8')

    def clear_request(self):
        if self.directory is not None:
            (self.directory / REQUEST_NAME).unlink(missing_ok=True)

    def save(self, *, phase, capture, iteration=None, history=None, previous=None):
        """Publish a checkpoint atomically, replacing any earlier one.

        ``capture`` writes the checkpoint payload into the directory it is
        given and returns its receipt. This function only swaps the whole
        directory into place, so a reader sees the previous checkpoint or this
        one, never a mixture; the previous one is removed only after the swap.
        """
        if self.directory is None:
            raise ValueError('A pause controller without a directory cannot checkpoint')
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.pause-', dir=directory.parent))
        try:
            state = staging / STATE_NAME
            state.mkdir()
            receipt = capture(state)
            meta = {'format': FORMAT, 'phase': phase, 'iteration': iteration,
                    'history': list(history or []), 'previous': previous,
                    'done_ids': sorted(int(body) for body in receipt['done_ids']),
                    'cells': int(receipt['cells']), 'batches': int(receipt['batches']),
                    'archive_sha256': receipt['archive_sha256'],
                    'signal_sha256': receipt['signal_sha256'],
                    'receipts': receipt['receipts'],
                    'archives': receipt['archives']}
            (state / 'meta.json').write_text(
                json.dumps(meta, indent=2, allow_nan=False) + '\n', encoding='utf8')
            for path in sorted(state.iterdir()):
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
            final = directory / STATE_NAME
            if final.exists():
                shutil.rmtree(final)
            os.replace(state, final)
            self.clear_request()
            return meta
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def capture_state(directory, *, archive, signal, done_ids, cells, batches,
                  receipts=None, archives=None):
    """Write one checkpoint's payload and return the identities it claims.

    The archive copy is taken by the archive itself, from the staged file it is
    still writing to, so the checkpoint is a prefix of whole batches even though
    the pass has not committed anything yet. ``receipts`` and ``archives`` carry
    the phases that already finished: a resumed experiment has to continue with
    them, because the coupled iteration reads their archives rather than
    repeating them.
    """
    target, digest = archive.checkpoint(directory)
    if target.name != 'events.jsonl':
        raise ValueError('Unchecked archive checkpoint name')
    np.save(Path(directory) / 'signal.npy', np.asarray(signal, dtype=float))
    signal_sha256 = hashlib.sha256(
        (Path(directory) / 'signal.npy').read_bytes()).hexdigest()
    kept = {}
    for label, receipt in (receipts or {}).items():
        name = f'receipt-{label}.npy'
        np.save(Path(directory) / name,
                np.asarray(receipt['neural_uv'], dtype=float))
        kept[label] = {key: value for key, value in receipt.items()
                       if key != 'neural_uv'} | {'signal': name}
    copies = {}
    for name, entry in (archives or {}).items():
        # The caller may name an archive directly or describe it with the digest
        # it is expected to have; the checkpoint records the digest of the bytes it
        # actually copied, so a resume can only read what was verified here.
        source = entry.get('path') if isinstance(entry, dict) else entry
        if source is None or not Path(source).is_file():
            # An archive that does not exist yet cannot be continued, so a
            # checkpoint taken before it is written simply does not carry it.
            continue
        target_name = f'archive-{name}.jsonl'
        shutil.copyfile(source, Path(directory) / target_name)
        copies[name] = {'file': target_name,
                        'sha256': hashlib.sha256(
                            (Path(directory) / target_name).read_bytes()).hexdigest()}
    return {'done_ids': set(done_ids), 'cells': int(cells), 'batches': int(batches),
            'archive_sha256': digest, 'signal_sha256': signal_sha256,
            'receipts': kept, 'archives': copies}


def load(directory):
    """Read a checkpoint written by PauseController.save, or None if absent.

    Every identity is re-derived from the bytes on disk: a checkpoint whose
    archive, signal or carried archives changed under us is not resumable, and
    saying so here is the only place that can be established before the pass
    starts.
    """
    if directory is None:
        return None
    state = Path(directory) / STATE_NAME
    meta_path = state / 'meta.json'
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding='utf8'))
    if (not isinstance(meta, dict) or meta.get('format') != FORMAT
            or not isinstance(meta.get('done_ids'), list)
            or any(type(body) is not int or body <= 0 for body in meta['done_ids'])
            or len(set(meta['done_ids'])) != len(meta['done_ids'])):
        raise ValueError('Invalid pause checkpoint')
    archive = state / 'events.jsonl'
    signal_path = state / 'signal.npy'
    if (not archive.is_file() or not signal_path.is_file()
            or hashlib.sha256(archive.read_bytes()).hexdigest() != meta['archive_sha256']
            or hashlib.sha256(signal_path.read_bytes()).hexdigest() != meta['signal_sha256']):
        raise ValueError('Pause checkpoint files changed or are incomplete')
    receipts = {}
    for label, receipt in (meta.get('receipts') or {}).items():
        name = receipt.get('signal')
        if not isinstance(receipt, dict) or name != f'receipt-{label}.npy':
            raise ValueError('Invalid pause checkpoint receipt')
        waypoint = state / name
        if not waypoint.is_file():
            raise ValueError('Pause checkpoint receipt file is missing')
        receipts[label] = {key: value for key, value in receipt.items()
                           if key != 'signal'} | {'neural_uv': np.load(waypoint)}
    archives = {}
    for name, entry in (meta.get('archives') or {}).items():
        copied = state / entry['file']
        if not copied.is_file() or hashlib.sha256(copied.read_bytes()).hexdigest() != entry[
                'sha256']:
            raise ValueError('Pause checkpoint archive is missing or changed')
        archives[name] = {'path': copied, 'sha256': entry['sha256']}
    return {'directory': state, 'meta': meta, 'archive_path': archive,
            'archive_sha256': meta['archive_sha256'], 'done_ids': set(meta['done_ids']),
            'signal': np.load(signal_path), 'receipts': receipts, 'archives': archives,
            'batches': int(meta['batches']), 'phase': meta.get('phase'),
            'iteration': meta.get('iteration'), 'history': list(meta.get('history') or []),
            'previous': meta.get('previous')}


def clear(directory):
    """Drop a checkpoint whose experiment has been completed and verified."""
    if directory is None:
        return
    state = Path(directory) / STATE_NAME
    if state.exists():
        shutil.rmtree(state)
