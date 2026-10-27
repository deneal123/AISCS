"""Rebuild the registered graph from primary files without changing a live graph."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    resources = Path(__file__).resolve().parents[1] / "tools/connectome"
    source_hash = hashlib.sha256((resources / "upstream_data.py").read_bytes()).hexdigest()
    if source_hash != "1c5189f6eaaff3f4a0525f6ced9124b02bb752057291681acc67800509a5a243":
        raise ValueError("Pinned graph compiler checksum mismatch")
    spec = importlib.util.spec_from_file_location(
        "registered_upstream", resources / "upstream_data.py"
    )
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    expected = json.loads((resources / "registered-manifest.json").read_text(encoding="utf-8"))
    expected_hash = "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2"
    annotations_hash = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"

    def verify(graph):
        if upstream.sha256(graph / "manifest.json") != expected_hash:
            raise ValueError("Manifest mismatch")
        for name, digest in expected["arrays"].items():
            if upstream.sha256(graph / name) != digest:
                raise ValueError("Array mismatch: " + name)
        if upstream.sha256(graph / "neurons.feather") != annotations_hash:
            raise ValueError("Annotations mismatch")

    output = args.output.resolve()
    target = output / "graph"
    if target.exists():
        verify(target)
        print(json.dumps({"state": "verified_existing", "manifest_sha256": expected_hash}))
        return
    raw = (args.raw or output / "raw").resolve()
    raw.mkdir(parents=True, exist_ok=True)
    for name, size, digest in upstream.SOURCES.values():
        path = raw / name
        if path.is_file() and path.stat().st_size == size and upstream.sha256(path) == digest:
            continue
        if args.offline:
            raise FileNotFoundError("Missing or invalid primary file: " + name)
        part = raw / (name + ".part")
        for attempt in range(2):
            try:
                offset = part.stat().st_size if part.exists() else 0
                if offset >= size:
                    part.unlink()
                    offset = 0
                request = Request(
                    upstream.BASE_URL + name,
                    headers={"Range": f"bytes={offset}-"} if offset else {},
                )
                with urlopen(request, timeout=90) as response:
                    if offset and response.status != 206:
                        offset = 0
                    if offset and not response.headers.get("Content-Range", "").startswith(
                        f"bytes {offset}-"
                    ):
                        raise RuntimeError("Invalid download range")
                    with part.open("ab" if offset else "wb") as stream:
                        while block := response.read(4 << 20):
                            stream.write(block)
                if part.stat().st_size != size or upstream.sha256(part) != digest:
                    part.unlink()
                    raise RuntimeError("Primary file checksum mismatch: " + name)
                os.replace(part, path)
                break
            except (OSError, RuntimeError):
                if attempt == 1:
                    raise
    # Upstream download() now only verifies the three complete files. It cannot
    # enter its original retry loop; acquisition above is bounded to two tries.
    staging = output / ".preparation"
    staging.mkdir(parents=True, exist_ok=True)
    upstream.prepare(staging, raw)
    verify(staging / "graph")
    os.replace(staging / "graph", target)
    print(json.dumps({"state": "published", "manifest_sha256": expected_hash}))


if __name__ == "__main__":
    main()
