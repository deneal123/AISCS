"""Durable cache for the two stimulus-only replays of a full-population experiment.

A full ЦНС experiment replays the whole population four times: an initial pass
with the stimulus and no feedback, a paired control pass with the stimulus off,
then two coupled iterations. The first two passes depend only on the experiment
configuration and the stimulus waveform, never on the feedback schedule, so on a
repeat experiment they can be restored instead of recomputed.

Restored passes are never silent: every cached entry stores the digests of its
inputs and of its own archive, and the caller re-verifies them before use. The
cache only shortens the wall clock of repeated measurements; it does not change
what a single experiment computes.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np

FORMAT = 'malecns-full-population-replay-cache-v1'
_EVENT = 'events.jsonl'
_TRACE = 'signals.npy'
_META = 'meta.json'
# 'full_control_branch' caches the whole paired-control branch (its initial pass
# plus its converged feedback iteration), which is a function of the experiment
# configuration alone: the control stimulus is identically zero. The coupled
# feedback branch is equally closed once both starting archives exist, so it is
# cached under 'full_feedback_branch' keyed by their digests.
_PHASES = ('full_active', 'full_control', 'full_control_branch', 'full_feedback_branch')


def _digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def pass_key(phase, stimulus, *, graph_sha256, configuration_sha256, baseline_sha256,
             replay_options):
    """Hash every input that can change the result of a stimulus-only pass."""
    if phase not in _PHASES:
        raise ValueError('Unsupported cached replay phase')
    values = np.ascontiguousarray(np.asarray(stimulus, dtype='<f8'))
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError('Invalid cached replay stimulus')
    # Options that reach the solver and can change its arithmetic. Callbacks and
    # archive paths are excluded: they never affect the numerical result.
    ignored = {'batch_progress', 'check_cancelled', 'event_path', 'audited_sources',
               'metadata_factory', 'expected_ids', 'params', 'time_ms'}
    settings = {str(key): value for key, value in replay_options.items()
                if key not in ignored and isinstance(value, (int, float, str, bool, list, dict))}
    payload = {'format': FORMAT, 'phase': phase, 'graph_sha256': graph_sha256,
               'configuration_sha256': configuration_sha256,
               'baseline_schedule_sha256': baseline_sha256,
               'stimulus': hashlib.sha256(values.tobytes()).hexdigest(),
               'samples': int(values.size), 'settings': settings}
    return hashlib.sha256(_canonical(payload).encode('utf8')).hexdigest()


class ReplayPassCache:
    """Store and restore completed stimulus-only passes, verified on every read."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def _entry(self, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('Invalid cached replay key')
        return self.directory / key[:2] / key

    def load(self, key, event_path):
        """Copy a verified cached archive into place; return its replay receipt."""
        entry = self._entry(key)
        meta_path = entry / _META
        if not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            return None
        if (not isinstance(meta, dict) or meta.get('format') != FORMAT
                or meta.get('key') != key
                or not isinstance(meta.get('event_sha256'), str)
                or not (entry / _EVENT).is_file() or not (entry / _TRACE).is_file()):
            return None
        # A corrupted or half-written entry must look like a miss, never like a
        # measurement: the archive digest is verified before anything is copied.
        if _digest_file(entry / _EVENT) != meta['event_sha256']:
            return None
        trace = np.asarray(np.load(entry / _TRACE), dtype=float).copy()
        if trace.ndim != 1 or not np.isfinite(trace).all():
            return None
        if (type(meta.get('cells')) is not int or meta['cells'] < 1
                or not isinstance(meta.get('solver_kernels'), dict)
                or not isinstance(meta.get('endpoint_relocation'), (dict, type(None)))
                or not isinstance(meta.get('extra'), (dict, type(None)))):
            return None
        shutil.copyfile(entry / _EVENT, event_path)
        return {'event_sha256': meta['event_sha256'], 'neural_uv': trace,
                'cells': meta['cells'], 'solver_kernels': meta['solver_kernels'],
                'endpoint_relocation': meta.get('endpoint_relocation'),
                'extra': meta.get('extra'), 'replay_cache_key': key}


    def save(self, key, event_path, result, *, extra=None):
        """Publish one completed pass atomically after its archive is final."""
        entry = self._entry(key)
        meta = {'format': FORMAT, 'key': key,
                'event_sha256': result['event_sha256'],
                'cells': int(result['cells']),
                'solver_kernels': result['solver_kernels'],
                'endpoint_relocation': result.get('endpoint_relocation'),
                'extra': extra}
        trace = np.asarray(result['neural_uv'], dtype=float)
        if trace.ndim != 1 or not np.isfinite(trace).all():
            raise ValueError('Invalid cached replay trace')
        self.directory.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f'.{key[:8]}-', dir=self.directory))
        try:
            shutil.copyfile(event_path, scratch / _EVENT)
            # np.save would append ".npy" to a Path, so write through a handle.
            with (scratch / _TRACE).open('wb') as stream:
                np.save(stream, trace)
            (scratch / _META).write_text(_canonical(meta) + '\n', encoding='utf8')
            entry.parent.mkdir(parents=True, exist_ok=True)
            if entry.exists():
                shutil.rmtree(entry, ignore_errors=True)
            os.replace(scratch, entry)
        finally:
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)
        return key
