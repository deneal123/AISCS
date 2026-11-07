"""Check current per-contact anchors against the immutable FlyBody source mesh."""

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from service.contracts import SimulationConfig

MESH_SHA256 = "2c7f3b44f2b3fccaaa267f8afc155558520ecf9514b6b6b385363ed5d1ba2344"
ASSET_ID = "flybody-sim003-fdbbd866-rest-v1"


@lru_cache(maxsize=1)
def thorax_mesh():
    raw = Path(__file__).with_name("flybody-thorax.bin").read_bytes()
    if len(raw) != 329640 or hashlib.sha256(raw).hexdigest() != MESH_SHA256:
        raise ValueError("Registered thorax geometry is unavailable or damaged")
    vertices = np.frombuffer(raw, dtype="<f4", count=27474).reshape(-1, 3)
    faces = np.frombuffer(raw, dtype="<u4", offset=109896).reshape(-1, 3)
    if faces.shape != (18312, 3) or int(faces.max()) >= len(vertices):
        raise ValueError("Registered thorax geometry is invalid")
    return vertices, faces


def validate_surface_anchors(config: SimulationConfig):
    context = config.placement.registration
    anchors = context.surface_anchors if context else None
    if not anchors or not (anchors.electrode or anchors.reference):
        return
    if context.mesh_asset_id != ASSET_ID:
        raise ValueError("Surface anchor geometry is unavailable for this mesh")
    vertices, faces = thorax_mesh()
    for name in ("electrode", "reference"):
        anchor = getattr(anchors, name)
        if not anchor:
            continue
        triangle = vertices[faces[anchor.triangle]].astype(np.float64)
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        length = np.linalg.norm(normal)
        if not np.isfinite(length) or length < 1e-12:
            raise ValueError("Surface anchor triangle is degenerate")
        point = np.asarray(anchor.barycentric) @ triangle
        expected_um = (point - np.asarray(context.origin_mm)) * 1000 + normal / length * 25
        actual_um = np.asarray(getattr(config.placement, name).xyz())
        if not np.allclose(expected_um, actual_um, rtol=0, atol=0.01):
            raise ValueError(f"{name}: coordinates do not match the registered surface anchor")
