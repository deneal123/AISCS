"""Resume acquisition of registered MaleCNS skeletons with bounded concurrency.

Source files are scientific data, not Python packages. Use an ignored work
directory; do not commit downloaded skeletons or assume missing files exist.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.morphology import neurite_landmark  # noqa: E402

BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/"
# Same registered graph manifest as service.infrastructure.connectome.dataset.
MANIFEST_SHA256 = "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2"


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 << 20), b""):
            result.update(block)
    return result.hexdigest()


def registered_ids(ids_path: Path, manifest_path: Path) -> list[int]:
    if sha256(manifest_path) != MANIFEST_SHA256:
        raise ValueError("Graph manifest does not match the registered generation")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256(ids_path) != manifest["arrays"]["ids.npy"]:
        raise ValueError("Graph neuron IDs do not match the registered manifest")
    ids = np.load(ids_path, allow_pickle=False)
    if ids.ndim != 1 or ids.dtype.kind not in "iu" or len(ids) != 166700:
        raise ValueError("Malformed registered neuron ID array")
    if np.any(ids <= 0) or np.any(np.diff(ids) <= 0):
        raise ValueError("Neuron IDs must be positive, unique and sorted")
    return [int(value) for value in ids]


def verified_receipt(directory: Path, body_id: int) -> bool:
    receipt = directory / "receipts" / f"{body_id}.json"
    raw = directory / "raw" / f"{body_id}.swc"
    if not receipt.is_file() or not raw.is_file():
        return False
    try:
        metadata = json.loads(receipt.read_text(encoding="utf-8"))
        return (
            isinstance(metadata, dict)
            and metadata.get("body_id") == body_id
            and metadata.get("url") == BASE + f"{body_id}.swc"
            and metadata.get("sha256") == sha256(raw)
        )
    except (ValueError, OSError):
        return False


def download(client: httpx.Client, directory: Path, body_id: int) -> dict:
    import httpx

    url = BASE + f"{body_id}.swc"
    errors = []
    for attempt in range(1, 3):
        try:
            response = client.get(url)
            response.raise_for_status()
            if str(response.url) != url:
                raise ValueError("Unexpected final source URL")
            raw = response.content
            landmarks = neurite_landmark(raw.decode("utf-8"))
            metadata = {"body_id": body_id, "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw), "etag": response.headers.get("etag"), "attempt": attempt,
                        **landmarks}
            destination = directory / "raw" / f"{body_id}.swc"
            temporary = destination.with_suffix(".swc.tmp")
            temporary.write_bytes(raw)
            temporary.replace(destination)
            receipt = directory / "receipts" / f"{body_id}.json"
            tmp_receipt = receipt.with_suffix(".json.tmp")
            tmp_receipt.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
            tmp_receipt.replace(receipt)
            return {"body_id": body_id, "state": "downloaded", "bytes": len(raw)}
        except (httpx.HTTPError, UnicodeError, ValueError) as error:
            errors.append(type(error).__name__)
    return {"body_id": body_id, "state": "unavailable", "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=8)
    parser.add_argument("--limit", type=int, default=0, help="Maximum new IDs; 0 means all")
    args = parser.parse_args()
    import httpx

    if args.limit < 0 or args.existing.resolve() == args.output.resolve():
        raise ValueError("Limit must be nonnegative and directories distinct")
    ids = registered_ids(args.ids, args.manifest)
    for child in ("raw", "receipts"):
        (args.output / child).mkdir(parents=True, exist_ok=True)
    started, skipped, completed, failures, downloaded_bytes = time.monotonic(), 0, 0, 0, 0
    remaining = []
    for body_id in ids:
        if verified_receipt(args.existing, body_id) or verified_receipt(args.output, body_id):
            skipped += 1
        elif not args.limit or len(remaining) < args.limit:
            remaining.append(body_id)
    print(json.dumps({"registered": len(ids), "verified_existing": skipped,
                      "queued": len(remaining)}), flush=True)
    failure_path = args.output / "failures.jsonl"
    with httpx.Client(timeout=httpx.Timeout(45, connect=20), follow_redirects=True,
                      limits=httpx.Limits(max_connections=args.workers),
                      headers={"User-Agent": "AISCS-MaleCNS-morphology/0.1"}) as client, \
            concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool, \
            failure_path.open("a", encoding="utf-8") as failure_log:
        iterator = iter(remaining)
        pending = set()
        for _ in range(min(args.workers * 2, len(remaining))):
            pending.add(pool.submit(download, client, args.output, next(iterator)))
        while pending:
            done, pending = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                result = future.result()
                completed += 1
                if result["state"] == "unavailable":
                    failures += 1
                    failure_log.write(json.dumps(result) + "\n")
                    failure_log.flush()
                else:
                    downloaded_bytes += result["bytes"]
                body_id = next(iterator, None)
                if body_id is not None:
                    pending.add(pool.submit(download, client, args.output, body_id))
            if completed and completed % 100 < len(done):
                print(json.dumps({"completed": completed, "failures": failures,
                                  "seconds": round(time.monotonic() - started, 1)}), flush=True)
    result = {"registered": len(ids), "verified_existing": skipped, "completed": completed,
              "failures": failures, "bytes": downloaded_bytes,
              "seconds": round(time.monotonic() - started, 1), "limited": bool(args.limit)}
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
