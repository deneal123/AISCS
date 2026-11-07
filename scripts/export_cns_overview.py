"""Build bounded source-SWC line samples for an overview of the registered CNS.

This is level of detail: sampled original edges are not complete morphologies,
synapse locations, conduction paths, or an anatomical body registration.
The full-resolution SWCs remain separately available by neuron ID.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_full_morphology import (  # noqa: E402
    BASE,
    MANIFEST_SHA256,
    registered_ids,
)


def sample_swc_edges(swc: str, limit: int) -> list[tuple[tuple[float, ...], tuple[float, ...]]]:
    """Sample evenly spaced real parent-child edges, never interpolate new edges."""
    if limit < 1:
        raise ValueError("Edge limit must be positive")
    rows = [
        line.split()
        for line in swc.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    points = {int(row[0]): tuple(float(v) * 0.008 for v in row[2:5]) for row in rows}
    edges = [(points[int(row[6])], points[int(row[0])]) for row in rows if int(row[6]) != -1]
    count = min(limit, len(edges))
    if count == 0:
        return []
    # Midpoint sampling is deterministic and avoids over-emphasizing first edges.
    return [edges[((2 * i + 1) * len(edges)) // (2 * count)] for i in range(count)]


def export_chunk(
    ids: list[int], offset: int, directories: list[Path], limit: int
) -> tuple[bytes, int]:
    output = bytearray()
    cells_with_edges = 0
    for position, body_id in enumerate(ids):
        raw = None
        for directory in directories:
            try:
                candidate = (directory / "raw" / f"{body_id}.swc").read_bytes()
                receipt = json.loads((directory / "receipts" / f"{body_id}.json").read_text())
                if (
                    isinstance(receipt, dict)
                    and receipt.get("body_id") == body_id
                    and receipt.get("url") == BASE + f"{body_id}.swc"
                    and receipt.get("sha256") == hashlib.sha256(candidate).hexdigest()
                ):
                    raw = candidate
                    break
            except (OSError, ValueError):
                continue
        if raw is None:
            raise ValueError(f"Missing or corrupt skeleton {body_id}")
        edges = sample_swc_edges(raw.decode("utf-8"), limit)
        cells_with_edges += bool(edges)
        for first, last in edges:
            output.extend(struct.pack("<Iffffff", offset + position, *first, *last))
    return gzip.compress(output, compresslevel=6, mtime=0), cells_with_edges


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--edges-per-neuron", type=int, default=8, choices=range(1, 33))
    parser.add_argument("--chunk-size", type=int, default=10000, choices=range(1, 10001))
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    ids = registered_ids(args.ids, args.manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "manifest.json").exists():
        raise ValueError("Output already contains a published overview")
    chunks = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for offset in range(0, len(ids), args.chunk_size):
            subset = ids[offset : offset + args.chunk_size]
            future = pool.submit(
                export_chunk, subset, offset, args.directory, args.edges_per_neuron
            )
            futures[future] = (offset, len(subset))
        processed = 0
        for future in concurrent.futures.as_completed(futures):
            offset, size = futures[future]
            binary, count = future.result()
            name = f"overview-{offset:06d}.bin.gz"
            path = args.output / name
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(binary)
            temp.replace(path)
            chunks.append(
                {
                    "file": name,
                    "start": offset,
                    "cells": size,
                    "cells_with_edges": count,
                    "bytes": len(binary),
                    "sha256": hashlib.sha256(binary).hexdigest(),
                }
            )
            processed += size
            print(json.dumps({"processed": processed, "total": len(ids)}), flush=True)
    chunks.sort(key=lambda chunk: chunk["start"])
    manifest = {
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "manifest_sha256": MANIFEST_SHA256,
        "source_frame": "MaleCNS native unmirrored EM",
        "units": "um",
        "method": "evenly-sampled-original-swc-edges-v1",
        "record_bytes": 28,
        "record_layout": "little-endian uint32 graph index, float32 x1 y1 z1 x2 y2 z2",
        "edges_per_neuron_max": args.edges_per_neuron,
        "chunks": chunks,
    }
    path = args.output / "manifest.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
