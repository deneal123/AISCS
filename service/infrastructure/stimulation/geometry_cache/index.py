"""Authenticate the source snapshot used by a packed morphology cache.

The independent audit is the caller's trust anchor; it describes a snapshot,
not subsequent mutations of the source SWC directory.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.dataset import digest


def audited_geometry_sources(database: Path, audit_path: Path, graph_ids, graph_sha256: str):
    """Return the ordered snapshot hashes only after independently auditing the index."""
    if not isinstance(graph_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', graph_sha256):
        raise ValueError('Invalid graph identity')
    raw_ids = list(graph_ids)
    if (not raw_ids or any(isinstance(value, bool | np.bool_)
                           or not isinstance(value, int | np.integer) for value in raw_ids)):
        raise ValueError('Invalid graph IDs')
    ids = [int(value) for value in raw_ids]
    if any(not 0 < value < 2**63 for value in ids) or any(
        a >= b for a, b in zip(ids, ids[1:], strict=False)
    ):
        raise ValueError('Invalid graph IDs')
    try:
        report = json.loads(audit_path.read_text(encoding='utf8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Independent source audit unavailable') from exc
    if (not isinstance(report, dict) or report.get('format') != 'malecns-bounds-audit-v1'
            or type(report.get('verified')) is not int or report['verified'] != len(ids)
            or report.get('graph_sha256') != graph_sha256
            or not isinstance(report.get('index_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', report['index_sha256'])):
        raise ValueError('Independent source audit does not match graph')
    try:
        if digest(database) != report['index_sha256']:
            raise ValueError('Source index changed since audit')
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            metadata = dict(db.execute('SELECT key, value FROM metadata'))
            algorithm = metadata.get('algorithm_sha256')
            if (metadata.get('format') != 'malecns-verified-bounds-v1'
                    or metadata.get('graph_sha256') != graph_sha256
                    or metadata.get('neurons') != str(len(ids))
                    or not isinstance(algorithm, str)
                    or not re.fullmatch(r'[a-f0-9]{64}', algorithm)):
                raise ValueError('Source index metadata does not match graph')
            rows = db.execute('SELECT body_id, status, sha256, min_x, max_x, min_y, max_y, '
                              'min_z, max_z FROM bounds ORDER BY body_id')
            result = {}
            for expected, row in zip(ids, rows, strict=True):
                if (row[0] != expected or row[1] != 'ok' or not isinstance(row[2], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', row[2])
                        or any(not isinstance(value, int | float) or not math.isfinite(value)
                               for value in row[3:])
                        or any(row[3 + axis * 2] > row[4 + axis * 2] for axis in range(3))):
                    raise ValueError('Source index is incomplete or invalid')
                result[expected] = row[2]
        if digest(database) != report['index_sha256']:
            raise ValueError('Source index changed while reading')
    except (OSError, sqlite3.Error) as exc:
        raise ValueError('Source index unavailable or invalid') from exc
    return result, report['index_sha256']
