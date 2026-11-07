"""Download missing-position MaleCNS skeletons, with resumable per-ID receipts.

Run using a Python environment with httpx. This only prepares scene landmarks;
it never changes graph connectivity, numerical currents, or accepted run files.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.morphology import neurite_landmark  # noqa: E402

BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/"
ANNOTATIONS = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8, choices=range(1, 17))
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    if inventory.get("annotations_sha256") != ANNOTATIONS:
        raise ValueError("Inventory is not bound to the registered annotation release")
    rows = inventory["missing"]
    ids = [r["bodyId"] for r in rows]
    if len(ids) != len(set(ids)) or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("Invalid inventory IDs")
    output = args.output.resolve()
    raw_dir, receipt_dir = output / "raw", output / "receipts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(exist_ok=True)
    started = time.monotonic()
    client = httpx.Client(
        timeout=httpx.Timeout(45, connect=20),
        limits=httpx.Limits(max_connections=args.workers, max_keepalive_connections=args.workers),
        headers={"User-Agent": "AISCS-MaleCNS-scene-landmarks/0.1"},
        follow_redirects=True,
    )

    def fetch(body_id):
        path = raw_dir / f"{body_id}.swc"
        receipt_path = receipt_dir / f"{body_id}.json"
        if receipt_path.exists() and path.exists():
            receipt = json.loads(receipt_path.read_text())
            if hashlib.sha256(path.read_bytes()).hexdigest() == receipt.get("sha256"):
                return receipt
        errors = []
        for attempt in range(2):
            try:
                response = client.get(BASE + f"{body_id}.swc")
                response.raise_for_status()
                raw = response.content
                landmark = neurite_landmark(raw.decode("utf-8"))
                path.write_bytes(raw)
                receipt = {
                    "body_id": body_id,
                    "url": str(response.url),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "etag": response.headers.get("etag"),
                    "attempt": attempt + 1,
                    **landmark,
                }
                receipt_path.write_text(
                    json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
                )
                return receipt
            except (httpx.HTTPError, UnicodeError, ValueError) as exc:
                errors.append(str(exc))
        return {"body_id": body_id, "errors": errors}

    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for index, receipt in enumerate(pool.map(fetch, ids), 1):
                results.append(receipt)
                if index % 100 == 0 or index == len(ids):
                    print(
                        json.dumps(
                            {
                                "done": index,
                                "total": len(ids),
                                "errors": sum("errors" in r for r in results),
                                "seconds": round(time.monotonic() - started, 1),
                            }
                        ),
                        flush=True,
                    )
    finally:
        client.close()
    result = {
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "annotations_sha256": ANNOTATIONS,
        "source": BASE,
        "source_page": "https://male-cns.janelia.org/download/",
        "source_units": "8 nm",
        "output_units": "um",
        "license": "CC-BY-4.0",
        "source_frame": "MaleCNS native unmirrored EM",
        "landmarks": results,
    }
    (output / "landmarks.json").write_text(
        json.dumps(result, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    errors = [r for r in results if "errors" in r]
    print(
        json.dumps(
            {
                "completed": len(results),
                "errors": len(errors),
                "bytes": sum(r.get("bytes", 0) for r in results),
            }
        ),
        flush=True,
    )
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
