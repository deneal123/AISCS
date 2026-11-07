"""Acquire the published MaleCNS neuropil meshes without changing source files."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = "https://storage.googleapis.com/flyem-male-cns/rois/"
DATASETS = {"fullbrain-roi-v4": 90, "malecns-vnc-neuropil-roi-v0": 24}


def fetch(url, *, head=False, maximum=64_000_000):
    with urlopen(Request(url, method="HEAD" if head else "GET"), timeout=90) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected source redirect")
        if head:
            return dict(response.headers.items())
        data = response.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Source object exceeds size limit")
        return data


def acquire_one(root: Path, dataset: str, segment: str, label: str, request=fetch):
    if (dataset not in DATASETS or not re.fullmatch(r"[1-9]\d*", segment)
            or not isinstance(label, str) or not label):
        raise ValueError("Invalid source region identity")
    base = ROOT + dataset + "/mesh/"
    manifest = json.loads(request(base + quote(segment + ":0", safe=":")))
    fragments = manifest.get("fragments")
    if (not isinstance(fragments, list) or len(fragments) != 1
            or not isinstance(fragments[0], str) or not fragments[0].endswith(".ngmesh")
            or "/" in fragments[0] or "\\" in fragments[0]):
        raise ValueError("Invalid source fragment")
    name = fragments[0]
    url = base + quote(name, safe="")
    headers = {key.lower(): value for key, value in request(url, head=True).items()}
    size = int(headers["content-length"])
    etag = headers.get("etag", "").strip('"')
    if not 0 < size <= 64_000_000 or not re.fullmatch(r"[0-9a-f]{32}", etag):
        raise ValueError("Source size or MD5 unavailable")
    folder = root / dataset
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{segment}.ngmesh"
    raw = target.read_bytes() if target.exists() else request(url, maximum=size)
    if len(raw) != size or hashlib.md5(raw).hexdigest() != etag:
        raise ValueError("Source mesh size or MD5 mismatch")
    if not target.exists():
        temporary = target.with_suffix(".part")
        temporary.write_bytes(raw)
        temporary.replace(target)
    return {"dataset": dataset, "id": segment, "label": label,
            "fragments": [{"name": name, "url": url, "bytes": size, "etag": etag}],
            "file": f"{dataset}/{segment}.ngmesh", "sha256": hashlib.sha256(raw).hexdigest(),
            "md5_verified": True}


def acquire(root: Path, *, workers=4, request=fetch):
    if not 1 <= workers <= 4:
        raise ValueError("Worker count must be between 1 and 4")
    pending = []
    for dataset, expected in DATASETS.items():
        data = json.loads(request(ROOT + dataset + "/segment_properties/info"))["inline"]
        ids = data["ids"]
        labels = next(item["values"] for item in data["properties"] if item["id"] == "source")
        if len(ids) != expected or len(labels) != expected or len(set(ids)) != expected:
            raise ValueError("Source region coverage changed")
        pending.extend((root, dataset, segment, label)
                       for segment, label in zip(ids, labels, strict=True))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda item: acquire_one(*item, request=request), pending))
    root.mkdir(parents=True, exist_ok=True)
    receipt = root / "inventory.json"
    if receipt.exists():
        if json.loads(receipt.read_text(encoding="utf-8")) != records:
            raise ValueError("Existing inventory differs from source; preserve it")
    else:
        temporary = root / "inventory.json.part"
        text = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(receipt)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    records = acquire(args.output, workers=args.workers)
    print(json.dumps({"regions": len(records),
                      "bytes": sum(r["fragments"][0]["bytes"] for r in records)}))


if __name__ == "__main__":
    main()
