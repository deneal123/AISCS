"""Experimental storage for one independently revalidated discretization receipt.

The caller supplies the original schedule, registered index, morphology and
policy on both write and read. This does not prove a solver used the receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from service.infrastructure.stimulation.feedback_discretization import (
    verify_feedback_discretization,
)

MAX_BYTES = 64 * 1024 * 1024
FORMAT = 'feedback-discretization-receipt-v1'


def _canonical(value):
    def json_keys(item):
        if isinstance(item, dict):
            result = {}
            for key, val in item.items():
                if type(key) not in (str, int):
                    raise ValueError('Invalid discretization archive key')
                name = str(key)
                if name in result:
                    raise ValueError('Ambiguous discretization archive key')
                result[name] = json_keys(val)
            return result
        if isinstance(item, list | tuple):
            return [json_keys(val) for val in item]
        return item

    try:
        return json.dumps(json_keys(value), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid discretization archive data') from exc


def _normalize_receipt(receipt):
    if not isinstance(receipt, dict) or not isinstance(receipt.get('targets'), dict):
        raise ValueError('Invalid discretization receipt')
    targets = receipt['targets']
    normalized = {}
    for key, value in targets.items():
        if (not isinstance(key, str) or not key.isascii() or not key.isdigit()
                or key.startswith('0') or str(int(key)) != key):
            raise ValueError('Invalid discretization target ID')
        normalized[int(key)] = value
    return {**receipt, 'targets': normalized}


def write_discretization_receipt(path: Path, schedule, receipt, index, directories, *, policy):
    """Verify first, then create a new bounded receipt without overwriting files."""
    if not isinstance(path, Path):
        raise ValueError('Invalid discretization archive path')
    verify_feedback_discretization(schedule, receipt, index, directories, policy=policy)
    payload = {'format': FORMAT,
               'schedule_sha256': hashlib.sha256(_canonical(schedule)).hexdigest(),
               'policy': policy, 'receipt': receipt}
    data = _canonical(payload)
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Discretization archive exceeds size limit')
    with path.open('xb') as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())
    return hashlib.sha256(data).hexdigest()


def read_discretization_receipt(path: Path, schedule, index, directories, *, policy):
    """Check identity and independently rebuild the saved receipt from its sources."""
    if (not isinstance(path, Path) or path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= MAX_BYTES):
        raise ValueError('Invalid discretization archive')
    data = path.read_bytes()
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Invalid discretization archive size')
    try:
        payload = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError('Non-finite discretization archive data')))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid discretization archive data') from exc
    if (not isinstance(payload, dict) or set(payload) != {
            'format', 'schedule_sha256', 'policy', 'receipt'} or payload['format'] != FORMAT
            or payload['schedule_sha256'] != hashlib.sha256(_canonical(schedule)).hexdigest()
            or payload['policy'] != policy or _canonical(payload) != data):
        raise ValueError('Discretization archive provenance mismatch')
    receipt = _normalize_receipt(payload['receipt'])
    return verify_feedback_discretization(schedule, receipt, index, directories, policy=policy)
