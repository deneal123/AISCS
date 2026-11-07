"""Read one source skeleton with its exact identity and integrity receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from service.infrastructure.connectome.morphology import neurite_landmark

BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/"
MAX_BYTES = 8 * 1024 * 1024


def read_skeleton(
    body_id: int, directories: list[Path], *, expected_sha256: str | None = None,
) -> dict:
    """Read a skeleton; an independently audited digest permits skipping re-parsing.

    The caller must establish that the digest belongs to a verified snapshot.
    The bytes and their source receipt are still checked on every read.
    """
    if type(body_id) is not int or not 0 < body_id < 2**63:
        raise ValueError("Invalid neuron ID")
    corrupt = False
    for directory in directories:
        path = directory / "raw" / f"{body_id}.swc"
        receipt = directory / "receipts" / f"{body_id}.json"
        if not path.is_file() or not receipt.is_file():
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Skeleton exceeds the single-neuron limit")
            raw = path.read_bytes()
            metadata = json.loads(receipt.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("Invalid skeleton receipt")
            sha = hashlib.sha256(raw).hexdigest()
            if (metadata.get("body_id") != body_id or metadata.get("sha256") != sha
                    or metadata.get("url") != BASE + f"{body_id}.swc"
                    or (expected_sha256 is not None and sha != expected_sha256)):
                raise ValueError("Skeleton receipt mismatch")
            text = raw.decode("utf-8")
            if expected_sha256 is not None:
                return {"body_id": str(body_id), "sha256": sha, "source": metadata["url"],
                        "source_units": "8 nm", "swc": text}
            verified = neurite_landmark(text)
            return {"body_id": str(body_id), "sha256": sha, "source": metadata["url"],
                    "source_units": "8 nm", "vertices": verified["vertices"],
                    "bounds_um": verified["bounds_um"], "swc": text}
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            corrupt = True
    if corrupt:
        raise ValueError("Skeleton or its receipt failed validation")
    raise FileNotFoundError("Skeleton has not been acquired")
