"""Audit an independent-cell windowed probe without claiming network validity."""

import argparse
import json
import math
from pathlib import Path

import numpy as np


def padded_segments(sizes, batch_size):
    """Estimate padded lanes only; does not estimate runtime or memory use."""
    return sum(max(sizes[start:start + batch_size]) * len(sizes[start:start + batch_size])
               for start in range(0, len(sizes), batch_size))


def audit(path, ids_path, receipts, *, limit):
    if type(limit) is not int or limit < 1:
        raise ValueError('Invalid expected cell count')
    ids = np.load(ids_path, mmap_mode='r')
    expected = []
    for value in ids:
        body = int(value)
        if (receipts / f'{body}.json').is_file():
            expected.append(body)
            if len(expected) == limit:
                break
    if len(expected) != limit:
        raise ValueError('Insufficient registered cells')
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines()]
    if len(rows) > limit:
        raise ValueError('Unexpected extra results')
    for body, row in zip(expected, rows, strict=False):
        receipt = json.loads((receipts / f'{body}.json').read_text(encoding='utf-8'))
        if (row.get('id') != body or row.get('sha256') != receipt.get('sha256')
                or type(row.get('segments')) is not int or row['segments'] < 1
                or type(row.get('clamped')) is not bool
                or any(type(row.get(key)) not in (int, float)
                       or not math.isfinite(row[key]) or row[key] < 0
                       for key in ('prepare_seconds', 'seconds', 'peak_rss_kib', 'max_abs_uv'))
                or row['prepare_seconds'] > row['seconds']):
            raise ValueError(f'Invalid result for cell {body}')
    sizes = [row['segments'] for row in rows]
    return {'completed': len(rows), 'expected': limit, 'complete': len(rows) == limit,
            'segments': sum(row['segments'] for row in rows),
            'estimated_padded_segments_batches_of_4': padded_segments(sizes, 4),
            'estimated_padded_segments_sorted_batches_of_4': padded_segments(sorted(sizes), 4),
            'sum_prepare_seconds': sum(row['prepare_seconds'] for row in rows),
            'sum_cell_seconds': sum(row['seconds'] for row in rows),
            'clamped_ids': [row['id'] for row in rows if row['clamped']],
            'max_peak_rss_kib': max((row['peak_rss_kib'] for row in rows), default=0),
            'scope': 'independent cells; no coupled network or biological validation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('ids', type=Path)
    parser.add_argument('receipts', type=Path)
    parser.add_argument('--limit', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.results, args.ids, args.receipts, limit=args.limit), indent=2))


if __name__ == '__main__':
    main()
