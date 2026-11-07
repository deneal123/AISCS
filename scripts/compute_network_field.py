"""Compute resumable field-only summaries for the registered MaleCNS graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.infrastructure.stimulation.field_summary_compute import compute  # noqa: E402

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-um", type=float, nargs=3, required=True)
    parser.add_argument("--return-um", type=float, nargs=3, required=True)
    parser.add_argument("--current-na", type=float, required=True)
    parser.add_argument("--conductivity-s-m", type=float, required=True)
    parser.add_argument("--clearance-um", type=float, required=True)
    parser.add_argument("--allow-degenerate", action="store_true")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel processes (1–8); output order remains deterministic")
    parser.add_argument("--field-backend", choices=("cpu", "gpu"), default="cpu")
    args = parser.parse_args()
    ids = registered_ids(args.graph / "ids.npy", args.graph / "manifest.json")
    config = {"source_um": args.source_um, "return_um": args.return_um,
              "current_na": args.current_na, "conductivity_s_m": args.conductivity_s_m,
              "clearance_um": args.clearance_um}
    def progress(done, total):
        print(f"{done}/{total}", file=sys.stderr, flush=True)

    count = compute(ids, args.morphology_dir, args.output, config, graph_hash=MANIFEST_SHA256,
                    progress=progress, allow_degenerate=args.allow_degenerate, workers=args.workers,
                    field_backend=args.field_backend)
    print(json.dumps({"processed": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
