"""Build the MaleCNS synapse batch index from verified public source data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.infrastructure.connectome.dataset import MANIFEST_SHA256  # noqa: E402
from service.infrastructure.connectome.synapse_index import (  # noqa: E402
    build_batch_index,
    file_digest,
)
from service.infrastructure.connectome.synapse_repository import SOURCE_MD5  # noqa: E402


def prepare(source: Path, graph: Path, output: Path, *, progress=None):
    """Accept only the registered graph and the pinned source table."""
    manifest_path = graph / "manifest.json"
    if file_digest(manifest_path, "sha256") != MANIFEST_SHA256:
        raise ValueError("Registered graph manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = graph / "ids.npy"
    if file_digest(ids, "sha256") != manifest["arrays"]["ids.npy"]:
        raise ValueError("Registered graph ID checksum mismatch")
    return build_batch_index(source, ids, output, SOURCE_MD5, progress=progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("Checking registered graph and source; this can take several minutes.", file=sys.stderr)
    def progress(stage, done, total):
        print(f"{stage}: {done}/{total}", file=sys.stderr, flush=True)

    result = prepare(args.source, args.graph, args.output, progress=progress)
    print(json.dumps({"neurons": result["neurons"], "batches": result["batches"]}))


if __name__ == "__main__":
    main()
