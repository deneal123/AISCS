"""Check grouped-cell summary against the sequential windowed baseline."""

import argparse
import json
import math
from pathlib import Path


def audit(baseline_path, grouped_path):
    baseline = [json.loads(line) for line in
                baseline_path.read_text(encoding='utf-8-sig').splitlines()]
    grouped = [json.loads(line) for line in
               grouped_path.read_text(encoding='utf-8-sig').splitlines()]
    seen = set()
    for row in grouped:
        index = row.get('index')
        if (type(index) is not int or not 0 <= index < len(baseline) or index in seen
                or row.get('id') != baseline[index].get('id')
                or type(row.get('clamped')) is not bool
                or row['clamped'] != baseline[index].get('clamped')
                or type(row.get('max_abs_uv')) not in (int, float)
                or not math.isfinite(row['max_abs_uv'])
                or not math.isclose(row['max_abs_uv'], baseline[index]['max_abs_uv'],
                                    rel_tol=1e-9, abs_tol=1e-10)):
            raise ValueError('Invalid or mismatched grouped cell result')
        seen.add(index)
    return {'completed': len(grouped), 'expected': len(baseline),
            'complete': len(grouped) == len(baseline),
            'scope': 'independent cells; maximum amplitudes only, not full traces'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('grouped', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.baseline, args.grouped), indent=2))


if __name__ == '__main__':
    main()
