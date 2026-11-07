"""Independently audit a field-only JSONL against the registered graph."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402
from service.infrastructure.stimulation.field_summary_audit import audit  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    ids = registered_ids(args.graph / "ids.npy", args.graph / "manifest.json")
    print(json.dumps(audit(args.input, ids, graph_hash=MANIFEST_SHA256,
                           allow_partial=args.allow_partial), ensure_ascii=False))


if __name__ == "__main__":
    main()
