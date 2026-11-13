"""Audit and compare two complete field-only summaries for registered MaleCNS."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.infrastructure.stimulation.field.summary_compare import compare  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--relative-tolerance', type=float, default=1e-9)
    parser.add_argument('--absolute-tolerance', type=float, default=1e-12)
    args = parser.parse_args()
    ids = registered_ids(args.graph / 'ids.npy', args.graph / 'manifest.json')
    result = compare(args.reference, args.candidate, ids, graph_hash=MANIFEST_SHA256,
                     rel_tol=args.relative_tolerance, abs_tol=args.absolute_tolerance)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['equal_within_tolerance'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
