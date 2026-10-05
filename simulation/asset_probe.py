"""Bounded checks/downloads of exact pinned assets, never invented replacements."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
from inventory import WORK, save

ASSETS = {
    "claude-plastic-weights": {
        "url": "https://media.githubusercontent.com/media/legacyindiesubmissions-ai/claude-fly/3a035275148e97539711728422548bffe2a77566/data/plastic_weights.pt",
        "filename": "plastic_weights.pt",
        "repository": "SIM-015",
        "download": False,
        "identity": "author-LFS-object-at-registered-commit",
    },
    "snedea-connectome": {
        "url": "https://raw.githubusercontent.com/snedea/flybrain/9191824d17871b7851645782d53d23f213ddb938/data/connectome.bin.gz",
        "filename": "connectome.bin.gz",
        "repository": "SIM-029",
        "download": True,
        "identity": "author-FlyWire-FAFB-v783-browser-export",
    },
    "flybox-manifest": {
        "url": "https://raw.githubusercontent.com/alextitonis/fly.ai/03358c075000af5379e405b244dd31f1a0fd1401/world/public/connectome/brain.json",
        "filename": "brain.json",
        "repository": "SIM-009",
        "download": True,
        "identity": "browser-MaleCNS-export-separate-from-flybox-source-commit",
    },
}


def validate_connectome(path):
    """Check the pinned worker's binary format using bounded streaming memory."""
    with gzip.open(path, "rb") as stream:
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("Truncated connectome header")
        neurons, edges = struct.unpack("<II", header)
        if neurons != 139255 or not 0 < edges <= 10_000_000:
            raise ValueError("Unexpected registered export dimensions")
        previous = -1
        remaining = edges
        while remaining:
            count = min(8192, remaining)
            block = stream.read(count * 12)
            if len(block) != count * 12:
                raise ValueError("Truncated edge records")
            for pre, post, weight in struct.iter_unpack("<IIf", block):
                if pre >= neurons or post >= neurons or not math.isfinite(weight):
                    raise ValueError("Invalid edge index or nonfinite weight")
                if pre < previous:
                    raise ValueError("Edges not sorted by presynaptic index")
                previous = pre
            remaining -= count
        remaining = neurons * 3
        while remaining:
            block = stream.read(min(65536, remaining))
            if not block:
                raise ValueError("Truncated region/group metadata")
            remaining -= len(block)
        if stream.read(1):
            raise ValueError("Unexpected trailing binary content")
    return {
        "status": "passed",
        "neurons": neurons,
        "edges": edges,
        "format": "little-endian uint32 N,E; E*(uint32,uint32,float32); N*(uint8,uint16)",
        "original_neuron_ids_in_binary": False,
        "biological_identity_verified": False,
    }


def validate_cached(name, asset):
    folder = WORK / asset["repository"] / "assets"
    receipt = folder / (name + ".json")
    if not receipt.exists():
        return {"status": "not_downloaded"}
    record = json.loads(receipt.read_text("utf-8"))
    if record["status"] != "available" or not asset["download"]:
        return {"status": "not_downloaded"}
    path = folder / asset["filename"]
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            sha.update(block)
    expected = record["attempts"][-1]["sha256"]
    if sha.hexdigest() != expected:
        raise ValueError("Registered asset hash mismatch")
    if name == "snedea-connectome":
        result = validate_connectome(path)
    else:
        content = json.loads(path.read_text("utf-8"))
        result = {"status": "passed", "scope": "JSON syntax and registered SHA256 only"}
        if not isinstance(content, dict):
            raise ValueError("Expected a manifest object")
    record["format_validation"] = result
    save(receipt, record)
    return result


def probe(name, asset):
    folder = WORK / asset["repository"] / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / (name + ".json")
    if receipt.exists():
        previous = json.loads(receipt.read_text("utf-8"))
        if previous["status"] == "available" or len(previous["attempts"]) >= 2:
            return previous
    else:
        previous = {"asset": asset, "status": "unresolved", "attempts": []}
    for attempt in range(len(previous["attempts"]) + 1, 3):
        record = {
            "attempt": attempt,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        target = folder / asset["filename"]
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            request = urllib.request.Request(
                asset["url"],
                method="GET" if asset["download"] else "HEAD",
                headers={"User-Agent": "Aspa-simulation-evaluation"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                record.update(
                    http_status=response.status,
                    final_url=response.url,
                    content_type=response.headers.get("Content-Type"),
                    content_length=response.headers.get("Content-Length"),
                )
                if asset["download"]:
                    maximum = 128 * 1024**2
                    if int(response.headers.get("Content-Length") or 0) > maximum:
                        raise ValueError(
                            "Asset exceeds bounded 128MiB probe; full scenario pending"
                        )
                    sha, size = hashlib.sha256(), 0
                    deadline = time.monotonic() + 120
                    with temporary.open("wb") as stream:
                        while block := response.read(1024**2):
                            if (
                                time.monotonic() > deadline
                                or size + len(block) > maximum
                            ):
                                raise ValueError("Bounded download limit reached")
                            stream.write(block)
                            sha.update(block)
                            size += len(block)
                    temporary.replace(target)
                    record.update(
                        bytes=size,
                        sha256=sha.hexdigest(),
                        path=target.relative_to(WORK.parents[2]).as_posix(),
                    )
                previous["status"] = "available"
        except (OSError, urllib.error.URLError, ValueError) as exc:
            record.update(error=str(exc), http_status=getattr(exc, "code", None))
            previous["status"] = "unavailable"
            if temporary.exists():
                temporary.unlink()  # exact owned partial file, inside .work only
        previous["attempts"].append(record)
        save(receipt, previous)
        if previous["status"] == "available":
            break
    return previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=list(ASSETS))
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Check existing files without network or simulation",
    )
    args = parser.parse_args()
    for name, asset in ASSETS.items():
        if not args.asset or name == args.asset:
            if args.validate_only:
                result = validate_cached(name, asset)
                print(name, result["status"], flush=True)
                continue
            result = probe(name, asset)
            print(
                name, result["status"], len(result["attempts"]), "attempts", flush=True
            )


if __name__ == "__main__":
    main()
