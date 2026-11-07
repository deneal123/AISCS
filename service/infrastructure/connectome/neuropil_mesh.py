"""Read a verified Neuroglancer legacy mesh in MaleCNS native nanometres."""

from __future__ import annotations

import hashlib
import struct

import numpy as np


def decode_legacy_mesh(raw: bytes, *, expected_sha256: str):
    """Validate exact bytes and triangle indices before exposing source geometry.

    This imports a neuropil segmentation surface, not an individual neurite,
    body registration, conductive tissue boundary, or dynamic model.
    """
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Neuropil mesh checksum mismatch")
    if len(raw) < 4:
        raise ValueError("Truncated neuropil mesh")
    count = struct.unpack_from("<I", raw)[0]
    vertex_bytes = count * 12
    remainder = len(raw) - 4 - vertex_bytes
    if count < 3 or remainder <= 0 or remainder % 12 != 0:
        raise ValueError("Invalid neuropil mesh layout")
    vertices = np.frombuffer(raw, dtype="<f4", count=count * 3, offset=4).reshape(-1, 3)
    faces = np.frombuffer(raw, dtype="<u4", offset=4 + vertex_bytes).reshape(-1, 3)
    if not np.isfinite(vertices).all() or (vertices < 0).any() or int(faces.max()) >= count:
        raise ValueError("Invalid neuropil mesh geometry")
    return {"vertices_um": vertices.astype(np.float64) / 1000,
            "faces": faces.copy(), "source_sha256": expected_sha256}
