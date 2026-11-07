"""Explicitly build an audited geometry snapshot for later GPU field calculations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.infrastructure.stimulation.geometry_cache.cache import build_cache  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--morphology-dir', type=Path, action='append', required=True)
    parser.add_argument('--source-index', type=Path, required=True)
    parser.add_argument('--source-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ids = registered_ids(args.graph / 'ids.npy', args.graph / 'manifest.json')

    def progress(done, total):
        if done % 1000 == 0 or done == total:
            print(f'{done}/{total}', file=sys.stderr, flush=True)

    checksum = build_cache(args.output, graph_ids=ids, graph_sha256=MANIFEST_SHA256,
                           source_index=args.source_index, source_audit=args.source_audit,
                           morphology_directories=args.morphology_dir, progress=progress)
    print(json.dumps({'neurons': len(ids), 'manifest_sha256': checksum,
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
