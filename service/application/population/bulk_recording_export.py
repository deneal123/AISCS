"""Atomic interchange for independent GPU population electrode recordings."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np


def export_bulk_recording(path, result, *, graph_sha256, configuration_sha256):
    """Save a verified numerical trace; caller owns scientific provenance."""
    for digest in (graph_sha256, configuration_sha256):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)):
            raise ValueError('Invalid recording provenance digest')
    if (not isinstance(result, dict) or type(result.get('cells')) is not int
            or result['cells'] < 1 or not isinstance(result.get('interpretation'), str)
            or 'no network feedback' not in result['interpretation']
            or not isinstance(result.get('replacement_receipts', []), list)):
        raise ValueError('Invalid independent recording')
    receipts = json.dumps(result.get('replacement_receipts', []), sort_keys=True,
                          separators=(',', ':'), allow_nan=False)
    time = np.asarray(result.get('time_ms'), dtype=np.float64)
    signal = np.asarray(result.get('neural_uv'), dtype=np.float64)
    if (time.ndim != 1 or len(time) < 2 or signal.shape != time.shape
            or not np.isfinite(time).all() or not np.isfinite(signal).all()
            or time[0] != 0 or np.any(np.diff(time) <= 0)):
        raise ValueError('Invalid independent recording samples')
    destination = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f'.{destination.name}.', suffix='.tmp',
                                     dir=destination.parent)
    try:
        with os.fdopen(fd, 'w+b') as stream:
            np.savez_compressed(stream, time_ms=time, neural_uv=signal,
                cells=np.array(result['cells'], dtype=np.int64),
                graph_sha256=np.array(graph_sha256),
                configuration_sha256=np.array(configuration_sha256),
                replacement_receipts_json=np.array(receipts),
                numerical_inputs_sha256=np.array(result.get('numerical_inputs_sha256', '')),
                interpretation=np.array(result['interpretation']))
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        os.replace(temporary, destination)
        temporary = None
        return {'sha256': digest, 'cells': result['cells'], 'samples': len(time)}
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_bulk_recording(path, *, sha256, graph_sha256, configuration_sha256):
    """Read a previously hashed independent recording from the same open file."""
    if (not isinstance(sha256, str) or len(sha256) != 64
            or any(char not in '0123456789abcdef' for char in sha256)):
        raise ValueError('Invalid recording digest')
    with Path(path).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != sha256:
            raise ValueError('Recording digest mismatch')
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as data:
            expected = {'time_ms', 'neural_uv', 'cells', 'graph_sha256', 'configuration_sha256',
                        'replacement_receipts_json', 'numerical_inputs_sha256', 'interpretation'}
            if set(data.files) != expected:
                raise ValueError('Invalid recording fields')
            if (str(data['graph_sha256']) != graph_sha256
                    or str(data['configuration_sha256']) != configuration_sha256):
                raise ValueError('Recording provenance mismatch')
            times = np.asarray(data['time_ms'], dtype=float)
            signal = np.asarray(data['neural_uv'], dtype=float)
            cells = np.asarray(data['cells'])
            interpretation = str(data['interpretation'])
            receipts = json.loads(str(data['replacement_receipts_json']))
            inputs_hash = str(data['numerical_inputs_sha256'])
            if (times.ndim != 1 or len(times) < 2 or signal.shape != times.shape
                    or not np.isfinite(times).all() or not np.isfinite(signal).all()
                    or times[0] != 0 or np.any(np.diff(times) <= 0)
                    or cells.shape != () or cells.dtype.kind not in 'iu' or int(cells) < 1
                    or 'no network feedback' not in interpretation
                    or not isinstance(receipts, list)
                    or (inputs_hash and (len(inputs_hash) != 64 or any(
                        char not in '0123456789abcdef' for char in inputs_hash)))):
                raise ValueError('Invalid independent recording contents')
            return {'time_ms': times.copy(), 'neural_uv': signal.copy(), 'cells': int(cells),
                    'replacement_receipts': receipts, 'interpretation': interpretation,
                    'numerical_inputs_sha256': inputs_hash}
