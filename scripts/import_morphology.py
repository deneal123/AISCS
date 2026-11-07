"""Verify locally downloaded MaleCNS SWCs against source metadata and register them.

The input is never modified. A receipt is published only after identity, remote
size and MD5, local SHA-256 and SWC geometry have been checked. Remote HEAD
requests transfer metadata only; skeleton files are not downloaded again.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import BASE, registered_ids, verified_receipt  # noqa: E402
from service.infrastructure.connectome.morphology import neurite_landmark  # noqa: E402

MAX_BYTES = 8 * 1024 * 1024


def import_one(client: httpx.Client, source: Path, output: Path, body_id: int) -> dict:
    path = source / f"{body_id}.swc"
    if not path.is_file():
        return {"body_id": body_id, "state": "missing"}
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("File exceeds the single-neuron size limit")
        raw = path.read_bytes()
        geometry = neurite_landmark(raw.decode("utf-8"))
        url = BASE + f"{body_id}.swc"
        response = client.head(url)
        response.raise_for_status()
        if str(response.url) != url:
            raise ValueError("Unexpected source URL")
        hashes = dict(
            part.strip().split("=", 1)
            for part in response.headers.get("x-goog-hash", "").split(",")
            if "=" in part
        )
        remote_md5 = hashes.get("md5")
        local_md5 = base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode(
            "ascii"
        )
        if (
            not remote_md5
            or remote_md5 != local_md5
            or int(response.headers.get("content-length", "-1")) != len(raw)
        ):
            raise ValueError("Source checksum or size mismatch")
        metadata = {
            "body_id": body_id,
            "url": url,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "etag": response.headers.get("etag"),
            "source_md5": remote_md5,
            "method_of_acquisition": "local-import-verified-against-source-head",
            **geometry,
        }
        destination = output / "raw" / f"{body_id}.swc"
        temporary = destination.with_suffix(".swc.tmp")
        temporary.write_bytes(raw)
        temporary.replace(destination)
        receipt = output / "receipts" / f"{body_id}.json"
        temporary_receipt = receipt.with_suffix(".json.tmp")
        temporary_receipt.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
        temporary_receipt.replace(receipt)
        return {"body_id": body_id, "state": "verified", "bytes": len(raw)}
    except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
        return {"body_id": body_id, "state": "failed", "error": str(error)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="Directory containing ID.swc files"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Separate ignored acquisition directory"
    )
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--limit", type=int, default=0, help="Maximum files to check; zero means all"
    )
    args = parser.parse_args()
    if not args.input.is_dir() or args.input.resolve() == args.output.resolve() or args.limit < 0:
        parser.error("Input must exist; input and output must differ; limit must be nonnegative")
    ids = registered_ids(args.ids, args.manifest)
    for child in ("raw", "receipts"):
        (args.output / child).mkdir(parents=True, exist_ok=True)
    counts = {"verified": 0, "missing": 0, "failed": 0, "skipped": 0}
    with (
        httpx.Client(timeout=45, follow_redirects=True) as client,
        (args.output / "import-failures.jsonl").open("a", encoding="utf-8") as log,
    ):
        for body_id in ids:
            if verified_receipt(args.output, body_id):
                counts["skipped"] += 1
                continue
            if args.limit and counts["verified"] + counts["failed"] >= args.limit:
                break
            result = import_one(client, args.input, args.output, body_id)
            counts[result["state"]] += 1
            if result["state"] == "failed":
                log.write(json.dumps(result, ensure_ascii=False) + "\n")
                log.flush()
    print(json.dumps(counts))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
