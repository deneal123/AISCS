"""Copy an independently checked field prefix after an interrupted final line."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_network_field import audit  # noqa: E402
from scripts.prepare_full_morphology import MANIFEST_SHA256, registered_ids  # noqa: E402


def recover(source: Path, destination: Path, ids, *, graph_hash: str):
    """Copy verified complete lines only; never rewrite the interrupted original.

    The source must be quiescent and end with an incomplete line. A bad complete
    record, unexpected footer, changed source, or existing destination fails
    closed. The returned SHA binds both the original and the recovered prefix.
    """
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError("Invalid or existing recovery destination")
    before = source.stat()
    source_hash = hashlib.sha256()
    prefix_hash = hashlib.sha256()
    dropped = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="field-recovery-", dir=destination.parent) as scratch:
        prefix = Path(scratch) / "prefix.jsonl"
        with source.open("rb") as incoming, prefix.open("xb") as outgoing:
            while True:
                line = incoming.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    raise ValueError("Field record exceeds recovery limit")
                source_hash.update(line)
                if line.endswith(b"\n"):
                    prefix_hash.update(line)
                    outgoing.write(line)
                else:
                    dropped = len(line)
                    if incoming.read(1):
                        raise ValueError("Incomplete field record is not final")
                    break
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Source changed during recovery")
        if not dropped:
            raise ValueError("Source has no incomplete final line")
        checked = audit(prefix, ids, graph_hash=graph_hash, allow_partial=True)
        if checked["complete"]:
            raise ValueError("Complete field file must not be recovered")
        with prefix.open("rb") as incoming, destination.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
    return {"processed": checked["processed"], "expected": checked["expected"],
            "source_sha256": source_hash.hexdigest(), "prefix_sha256": prefix_hash.hexdigest(),
            "discarded_incomplete_bytes": dropped, "chain_sha256": checked["chain_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    args = parser.parse_args()
    ids = registered_ids(args.graph / "ids.npy", args.graph / "manifest.json")
    print(json.dumps(recover(args.source, args.destination, ids, graph_hash=MANIFEST_SHA256)))
