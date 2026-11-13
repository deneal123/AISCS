"""Compare both GPU field-summary operators over a pinned complete snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.infrastructure.stimulation.field.fused_compare import compare_cache  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--geometry-cache', type=Path, required=True)
    parser.add_argument('--geometry-cache-sha256', required=True)
    parser.add_argument('--source-index', type=Path, required=True)
    parser.add_argument('--source-audit', type=Path, required=True)
    parser.add_argument('--reference-field', type=Path,
                        help='Optional previously audited field summary with matching parameters')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-um', type=float, nargs=3, required=True)
    parser.add_argument('--return-um', type=float, nargs=3, required=True)
    parser.add_argument('--current-na', type=float, required=True)
    parser.add_argument('--conductivity-s-m', type=float, required=True)
    parser.add_argument('--clearance-um', type=float, required=True)
    parser.add_argument('--allow-degenerate', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Comparison report already exists')
    ids = registered_ids(args.graph / 'ids.npy', args.graph / 'manifest.json')
    configuration = {key: getattr(args, key) for key in (
        'source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um')}
    cache = {'directory': args.geometry_cache,
             'expected_manifest_sha256': args.geometry_cache_sha256,
             'source_index': args.source_index, 'source_audit': args.source_audit}
    last_report = 0
    def progress(done, total):
        nonlocal last_report
        if done - last_report >= 1000 or done == total:
            print(f'{done}/{total}', file=sys.stderr, flush=True)
            last_report = done

    result = compare_cache(geometry_cache=cache, graph_ids=ids, graph_sha256=MANIFEST_SHA256,
                           configuration=configuration, allow_degenerate=args.allow_degenerate,
                           progress=progress, reference_field=args.reference_field)
    with args.output.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'neurons': result['neurons'], 'mismatches': result['mismatches'],
                      'reference_mismatches': result['reference_mismatches'],
                      'report': str(args.output)}))
    if result['mismatches'] or result['reference_mismatches']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
