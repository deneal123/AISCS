"""Compare audited field summaries without treating extrema as excitability."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from service.infrastructure.stimulation.field_summary_audit import audit


def _sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compare(reference: Path, candidate: Path, ids, *, graph_hash: str,
            rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> dict:
    """Audit complete files first; compare all metadata and summary extrema in order.

    This does not compare per-segment fields, prove excitation, or establish
    agreement with biological measurements. Concurrent file changes invalidate it.
    """
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (rel_tol, abs_tol)):
        raise ValueError('Invalid comparison tolerance')
    paths = [Path(reference), Path(candidate)]
    before = [_sha256(path) for path in paths]
    audits = [audit(path, ids, graph_hash=graph_hash) for path in paths]
    mismatches, examples, max_abs, max_relative, nonidentical = 0, [], 0., 0., 0
    with paths[0].open(encoding='utf-8') as left, paths[1].open(encoding='utf-8') as right:
        headers = [json.loads(left.readline()), json.loads(right.readline())]
        if (headers[0]['configuration'] != headers[1]['configuration']
                or headers[0].get('allow_degenerate') != headers[1].get('allow_degenerate')):
            raise ValueError('Field configurations or geometry policies differ')
        curvature = 'max_abs_curvature_signed_mv_per_um2'
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            row_a, row_b = json.loads(a), json.loads(b)
            if row_a.get('kind') == 'footer' or row_b.get('kind') == 'footer':
                if row_a.get('kind') != row_b.get('kind') or index != len(ids):
                    raise ValueError('Unexpected field footer')
                continue
            row_a.pop('chain_sha256', None)
            row_b.pop('chain_sha256', None)
            a_value, b_value = row_a.pop(curvature, None), row_b.pop(curvature, None)
            same_value = a_value is None and b_value is None
            if a_value is not None and b_value is not None:
                delta = abs(a_value - b_value)
                if not math.isfinite(delta):
                    raise ValueError('Field extrema difference overflow')
                max_abs = max(max_abs, delta)
                if delta:
                    nonidentical += 1
                    max_relative = max(max_relative, delta / max(abs(a_value), abs(b_value)))
                same_value = math.isclose(a_value, b_value, rel_tol=rel_tol, abs_tol=abs_tol)
            if row_a != row_b or not same_value:
                mismatches += 1
                if len(examples) < 20:
                    examples.append({'body_id': str(ids[index]), 'metadata_equal': row_a == row_b,
                                     'reference_extremum': a_value, 'candidate_extremum': b_value})
    after = [_sha256(path) for path in paths]
    if before != after:
        raise ValueError('Field file changed during comparison')
    return {'equal_within_tolerance': mismatches == 0, 'count': len(ids),
            'mismatch_count': mismatches, 'examples': examples, 'max_abs_extremum_delta': max_abs,
            'max_symmetric_relative_delta': max_relative, 'nonidentical_extrema': nonidentical,
            'relative_tolerance': rel_tol, 'absolute_tolerance': abs_tol,
            'reference_sha256': before[0], 'candidate_sha256': before[1],
            'reference_audit': audits[0], 'candidate_audit': audits[1],
            'interpretation': 'Field-summary comparison only; not validation of excitation.'}
