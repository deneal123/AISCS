#!/usr/bin/env python3
"""Reproducible asset exporter for the bundled FlyGym NeuroMechFly STL meshes.

Builds a single assembled, neutral-posed adult *Drosophila* scene for Three.js
from the real, pinned upstream artifacts of ``NeLy-EPFL/flygym`` at commit
``38c8ec61034cd59bc5ba0de20688d4a3c0000d60``.

Design constraints (see result.md)
----------------------------------
* No canonical edits, no sidecar mutation. Every input is read through
  ``git show HEAD:<path>`` as raw bytes (the STL meshes are sparse-excluded
  from the local worktree, so the worktree copy cannot be used).
* No external downloads. Only the pinned Git object store is read.
* Real geometry, real rigging. The scene is produced from the 39 bundled
  ``simplified_max2000faces`` STL parts plus the upstream ``rigging.yaml``
  (parent-relative body poses), the neutral pose files
  (``pose/neutral/*.yaml``), and ``visuals.yaml`` (colors).
* Left/right mirroring is explicit: the repository ships only left / centre
  meshes; right-side bodies reuse the left STL with ``scale=(1000, -1000, 1000)``
  and reversed winding, exactly as ``NeuroMechFly._add_mesh_assets`` does.
* STL units are metres; FlyGym simulates in millimetres (``SCALE = 1000``),
  so every vertex is scaled by 1000 before the body transform.

Usage
-----
    python export_fly.py [--repo R:/Aspa/simulations/sidecars/NeLy-EPFL--flygym]
                         [--commit 38c8ec61...] [--out <dir>]

Writes ``fly.json``, ``provenance.json`` and ``result.md`` next to the script
(or into ``--out``).

Requires: Python 3.10+, PyYAML. numpy is optional (a pure-Python matrix path is
used so the script runs in a minimal interpreter).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit(
        "PyYAML is required. Try: R:/Aspa/backend/.venv/Scripts/python.exe export_fly.py"
    )


# --------------------------------------------------------------------------
# Upstream pin
# --------------------------------------------------------------------------
EXPECTED_COMMIT = "38c8ec61034cd59bc5ba0de20688d4a3c0000d60"
DEFAULT_REPO = str(Path(__file__).resolve().parents[2] / "simulations/sidecars/NeLy-EPFL--flygym")

MODEL_DIR = "src/flygym/assets/model/neuromechfly"
RIGGING_PATH = f"{MODEL_DIR}/rigging.yaml"
VISUALS_PATH = f"{MODEL_DIR}/visuals.yaml"
MESH_DIR = f"{MODEL_DIR}/meshes/simplified_max2000faces"
LICENSE_PATH = "LICENSE"
PREFERRED_POSE = "roll_pitch_yaw"  # AxisOrder.ROLL_PITCH_YAW

# Neutron fly body frame: +X = forward (head), +Z = up, +Y = fly's left.
UP_AXIS = "+Z"
FORWARD_AXIS = "+X"
LEFT_AXIS = "+Y"

# FlyGym models the fly in millimetres: BaseFly.SCALE == 1000.
MJ_SCALE = 1000.0
# Simplified meshes carry at most this many faces (directory name).
MAX_FACES = 2000


# --------------------------------------------------------------------------
# Kinematic tree
# --------------------------------------------------------------------------
# These lists mirror the module constants in ``flygym/anatomy.py`` at the
# pinned commit (LEG_LINKS / ANTENNA_LINKS / PROBOSCIS_LINKS / ABDOMEN_LINKS and
# ALL_CONNECTED_SEGMENT_PAIRS).  They are validated against the keys of the
# upstream ``rigging.yaml`` at export time, so a drift in the pin is caught.
SIDES = ["l", "r"]
LEGS = [f"{side}{pos}" for side in SIDES for pos in "fmh"]
LEG_LINKS = [
    "coxa",
    "trochanterfemur",
    "tibia",
    "tarsus1",
    "tarsus2",
    "tarsus3",
    "tarsus4",
    "tarsus5",
]
ANTENNA_LINKS = ["pedicel", "funiculus", "arista"]
PROBOSCIS_LINKS = ["rostrum", "haustellum"]
ABDOMEN_LINKS = ["abdomen12", "abdomen3", "abdomen4", "abdomen5", "abdomen6"]
ROOT_SEGMENT = "c_thorax"

# RotationAxis convention in flygym.anatomy.RotationAxis:
#   pitch -> +Y, roll -> +Z, yaw -> +X
AXIS_VECTORS = {
    "pitch": (0.0, 1.0, 0.0),
    "roll": (0.0, 0.0, 1.0),
    "yaw": (1.0, 0.0, 0.0),
}
AXIS_ORDER = ["pitch", "roll", "yaw"]


def _chain(*args: str) -> list[tuple[str, str]]:
    return [(args[i], args[i + 1]) for i in range(len(args) - 1)]


def connected_segment_pairs() -> list[tuple[str, str]]:
    """Reconstruct ``ALL_CONNECTED_SEGMENT_PAIRS`` from ``anatomy.py``."""
    pairs: list[tuple[str, str]] = [("c_thorax", "c_head")]
    pairs += _chain("c_head", *(f"c_{lk}" for lk in PROBOSCIS_LINKS))
    pairs += _chain("c_thorax", *(f"c_{lk}" for lk in ABDOMEN_LINKS))
    pairs += [("c_head", f"{s}_eye") for s in SIDES]
    pairs += [
        edge
        for s in SIDES
        for edge in _chain("c_head", *(f"{s}_{lk}" for lk in ANTENNA_LINKS))
    ]
    pairs += [("c_thorax", f"{s}_wing") for s in SIDES]
    pairs += [("c_thorax", f"{s}_haltere") for s in SIDES]
    pairs += [
        edge
        for leg in LEGS
        for edge in _chain("c_thorax", *(f"{leg}_{lk}" for lk in LEG_LINKS))
    ]
    return pairs


def biological_axes(segment: str) -> list[str]:
    """Return the DoF axes present at a segment's joint to its parent.

    Mirrors ``JointPreset._get_all_biological_joints`` at the pinned commit:
    leg coxae keep pitch/roll/yaw, trochanterfemora keep pitch/roll (no yaw),
    all more distal leg links keep pitch only; every non-leg joint keeps
    pitch/roll/yaw.
    """
    pos, link = segment.split("_")
    if pos in LEGS:
        if link == "coxa":
            return ["pitch", "roll", "yaw"]
        if link == "trochanterfemur":
            return ["pitch", "roll"]
        return ["pitch"]
    return ["pitch", "roll", "yaw"]


def segment_side_signs(segment: str) -> dict[str, float]:
    """Sign applied to right-side joint angles.

    ``BaseFly.add_joints`` negates the joint *axis vector* for every non-pitch
    DoF on a right-side child (``if jointdof.child.pos[0] == "r" and not
    pitch: vec = -vec``).  A negated axis is equivalent to a negated angle, so
    the right side uses ``{pitch: +1, roll: -1, yaw: -1}``.  This is also what
    makes the assembled right side an exact mirror of the left.
    """
    if segment[0] == "r":
        return {"pitch": 1.0, "roll": -1.0, "yaw": -1.0}
    return {"pitch": 1.0, "roll": 1.0, "yaw": 1.0}


def build_children(pairs: Sequence[tuple[str, str]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for parent, child in pairs:
        children.setdefault(parent, []).append(child)
    return children


def traversal_order(children: dict[str, list[str]]) -> list[str]:
    """Deterministic breadth-first order from the root (matches DFS body set)."""
    order: list[str] = [ROOT_SEGMENT]
    queue: list[str] = [ROOT_SEGMENT]
    while queue:
        node = queue.pop(0)
        for child in children.get(node, []):
            order.append(child)
            queue.append(child)
    return order


# --------------------------------------------------------------------------
# Small pure-Python 3x3 linear algebra
# --------------------------------------------------------------------------
Matrix3 = list[list[float]]


def _matmul(a: Matrix3, b: Matrix3) -> Matrix3:
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]


def _matvec(a: Matrix3, v: Sequence[float]) -> tuple[float, float, float]:
    return tuple(  # type: ignore[return-value]
        sum(a[i][k] * v[k] for k in range(3)) for i in range(3)
    )


def rotation_matrix(axis: str, angle_rad: float) -> Matrix3:
    """Right-handed rotation about a +X/+Y/+Z axis by ``angle_rad``."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    if axis == "yaw":  # +X
        return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
    if axis == "pitch":  # +Y
        return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
    if axis == "roll":  # +Z
        return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    raise ValueError(f"unknown axis {axis!r}")


def quat_to_matrix(q: Sequence[float]) -> Matrix3:
    """Convert an MJCF ``(w, x, y, z)`` quaternion to a rotation matrix."""
    w, x, y, z = (float(v) for v in q)
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def matrix_to_quat_wxyz(m: Matrix3) -> list[float]:
    """Convert a rotation matrix to a normalized ``(w, x, y, z)`` quaternion."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    return [w / norm, x / norm, y / norm, z / norm]


# --------------------------------------------------------------------------
# Git-backed asset access (read-only)
# --------------------------------------------------------------------------
class GitRepo:
    """Read-only accessor for a pinned git checkout's object store."""

    def __init__(self, repo: str) -> None:
        self.repo = Path(repo)
        if not (self.repo / ".git").exists():
            raise FileNotFoundError(f"not a git repository: {self.repo}")

    def run(self, *args: str) -> bytes:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.decode(errors='replace').strip()}"
            )
        return proc.stdout

    def rev_parse(self, rev: str) -> str:
        return self.run("rev-parse", rev).decode().strip()

    def show(self, path: str, rev: str = "HEAD") -> bytes:
        """Return the raw bytes of ``rev:path`` (never touches the worktree)."""
        return self.run("show", f"{rev}:{path}")

    def list_tree(self, rev: str, path: str | None = None) -> list[str]:
        args = ["ls-tree", "-r", "--name-only", rev]
        if path is not None:
            args += ["--", path]
        out = self.run(*args)
        return [line for line in out.decode().splitlines() if line]

    def blob_sha1(self, path: str, rev: str = "HEAD") -> str:
        return self.rev_parse(f"{rev}:{path}")

    def text(self, path: str, rev: str = "HEAD") -> str:
        return self.show(path, rev).decode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# STL parsing
# --------------------------------------------------------------------------
def parse_stl(data: bytes) -> list[tuple[tuple[float, float, float], ...]]:
    """Parse an STL blob into a list of triangles (each 3 tuples of floats).

    Handles binary and ASCII STL.  Raises ``ValueError`` for anything else.
    """
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if len(data) == 84 + n * 50:
            tris = []
            for i in range(n):
                base = 84 + i * 50
                vals = struct.unpack("<12fH", data[base : base + 50])
                tris.append(
                    (
                        (vals[3], vals[4], vals[5]),
                        (vals[6], vals[7], vals[8]),
                        (vals[9], vals[10], vals[11]),
                    )
                )
            return tris
    return _parse_ascii_stl(data.decode("utf-8", errors="strict"))


def _parse_ascii_stl(text: str) -> list[tuple[tuple[float, float, float], ...]]:
    tris: list[tuple[tuple[float, float, float], ...]] = []
    verts: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            _, x, y, z = line.split()
            verts.append((float(x), float(y), float(z)))
            if len(verts) == 3:
                tris.append(tuple(verts))  # type: ignore[arg-type]
                verts = []
    if not tris:
        raise ValueError("not a recognised STL file")
    return tris


def mirror_triangles(
    tris: Iterable[tuple[tuple[float, float, float], ...]],
) -> list[tuple[tuple[float, float, float], ...]]:
    """Mirror across the XZ plane (negate Y) and reverse winding.

    Matches ``scale=(1000, -1000, 1000)`` in ``NeuroMechFly._add_mesh_assets``.
    Negating one axis flips handedness, so triangle winding is reversed to keep
    outward-facing normals consistent for rendering.
    """
    return [
        tuple((x, -y, z) for (x, y, z) in reversed(tri)) for tri in tris
    ]


# --------------------------------------------------------------------------
# YAML config loading
# --------------------------------------------------------------------------
def load_rigging(git: GitRepo) -> dict[str, dict[str, Any]]:
    return yaml.safe_load(git.text(RIGGING_PATH))


def load_visuals(git: GitRepo) -> dict[str, dict[str, Any]]:
    return yaml.safe_load(git.text(VISUALS_PATH))


def load_pose(git: GitRepo, name: str) -> tuple[list[str], dict[str, float]]:
    payload = yaml.safe_load(git.text(f"{MODEL_DIR}/pose/neutral/{name}.yaml"))
    order = list(payload["axis_order"])
    raw = payload["joint_angles"]
    if payload["angle_unit"] == "degree":
        angles = {k: math.radians(float(v)) for k, v in raw.items()}
    else:
        angles = {k: float(v) for k, v in raw.items()}
    return order, angles


# --------------------------------------------------------------------------
# Pose resolution (upstream semantics)
# --------------------------------------------------------------------------
def _left_name(name: str) -> str:
    """Map a right-side segment name to its left-side counterpart."""
    return ("l" + name[1:]) if name[0] == "r" else name


def joint_angle_rad(
    joint_angles: dict[str, float],
    parent: str,
    child: str,
    axis: str,
    side_signs: dict[str, float],
) -> float:
    """Resolve a joint angle exactly as FlyGym does.

    ``KinematicPose._mirror_pose_left2right_in_place`` copies any missing
    right-side angle from the identically-named left-side DoF, and
    ``BaseFly.add_joints`` negates the axis (i.e. the effective angle) for
    right-side non-pitch DoFs.
    """
    key = f"{parent}-{child}-{axis}"
    if key not in joint_angles:
        key = f"{_left_name(parent)}-{_left_name(child)}-{axis}"
    angle = float(joint_angles.get(key, 0.0))
    return angle * side_signs[axis]


def forward_kinematics(
    rigging: dict[str, dict[str, Any]],
    order: Sequence[str],
    joint_angles: dict[str, float],
    parents: dict[str, str | None],
    traversal: Sequence[str],
) -> tuple[dict[str, list[float]], dict[str, Matrix3]]:
    """Compute neutral world position / rotation for every body segment.

    Body ``pos``/``quat`` from ``rigging.yaml`` are parent-relative, exactly as
    in the MJCF: world rotation is the parent rotation composed with the body's
    neutral quaternion and the joint rotations in ``axis_order``; world position
    is the parent position plus the parent rotation applied to the local offset.
    Positions are in millimetres (the rigging is already in mm).
    """
    positions: dict[str, list[float]] = {}
    rotations: dict[str, Matrix3] = {}

    for segment in traversal:
        entry = rigging[segment]
        local_pos = [float(v) for v in entry["pos"]]
        local_rot = quat_to_matrix(entry["quat"])

        parent = parents[segment]
        if parent is None:
            positions[segment] = local_pos
            rotations[segment] = local_rot
            continue

        offset = _matvec(rotations[parent], local_pos)
        positions[segment] = [
            p + d for p, d in zip(positions[parent], offset)
        ]

        rot = _matmul(rotations[parent], local_rot)
        signs = segment_side_signs(segment)
        axes = biological_axes(segment)
        for axis in order:
            if axis not in axes:
                continue
            angle = joint_angle_rad(joint_angles, parent, segment, axis, signs)
            rot = _matmul(rot, rotation_matrix(axis, angle))
        rotations[segment] = rot

    return positions, rotations


def build_parents(pairs: Sequence[tuple[str, str]]) -> dict[str, str | None]:
    parents: dict[str, str | None] = {ROOT_SEGMENT: None}
    for parent, child in pairs:
        parents[child] = parent
    return parents


# --------------------------------------------------------------------------
# Colors (visuals.yaml, fnmatch semantics)
# --------------------------------------------------------------------------
def resolve_colors(
    segment_names: Sequence[str], visuals: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Assign exactly one visual set per segment using fnmatch, like FlyGym.

    ``BaseFly._parse_visuals_config`` raises if a geom matches zero or multiple
    visual sets; we reproduce the matching and fail loudly on ambiguity.
    """
    matches: dict[str, list[str]] = {name: [] for name in segment_names}
    for vis_name, vis_set in visuals.items():
        apply_to = vis_set.get("apply_to")
        patterns = [apply_to] if isinstance(apply_to, str) else list(apply_to or [])
        for pattern in patterns:
            for name in fnmatch.filter(list(segment_names), pattern):
                matches[name].append(vis_name)

    resolved: dict[str, dict[str, Any]] = {}
    for name, hits in matches.items():
        unique = sorted(set(hits))
        if len(unique) != 1:
            raise ValueError(
                f"expected exactly one visual set for {name}, got {unique}"
            )
        vis_set = visuals[unique[0]]
        material = vis_set["material"]
        rgba = [float(v) for v in material["rgba"]]
        resolved[name] = {
            "visual_set": unique[0],
            "rgba": rgba,
            "hex": "#{:02x}{:02x}{:02x}".format(
                *[max(0, min(255, round(c * 255))) for c in rgba[:3]]
            ),
            "specular": float(material.get("specular", 0.0)),
            "shininess": float(material.get("shininess", 0.0)),
            "opacity": rgba[3],
        }
    return resolved


# --------------------------------------------------------------------------
# Scene assembly
# --------------------------------------------------------------------------
def source_mesh_name(segment: str) -> str:
    """Left-side/centre STL used for a segment (right side mirrors the left)."""
    return f"l{segment[1:]}" if segment[0] == "r" else segment


def assemble_scene(
    git: GitRepo,
    rigging: dict[str, dict[str, Any]],
    colors: dict[str, dict[str, Any]],
    positions: dict[str, list[float]],
    rotations: dict[str, Matrix3],
    traversal: Sequence[str],
    parents: dict[str, str | None],
    precision: int = 4,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Build the flat Three.js scene: one named part per body segment.

    Every triangle vertex is scaled from metres to millimetres, transformed by
    the segment's neutral world pose, and rounded to ``precision`` decimals.
    Returns the scene dict and a cache of raw STL bytes used for hashing.
    """
    stl_cache: dict[str, bytes] = {}
    parts: list[dict[str, Any]] = []
    total_triangles = 0

    for segment in traversal:
        mesh_name = source_mesh_name(segment)
        mesh_path = f"{MESH_DIR}/{mesh_name}.stl"
        if mesh_path not in stl_cache:
            stl_cache[mesh_path] = git.show(mesh_path)
        triangles = parse_stl(stl_cache[mesh_path])

        mirrored = segment[0] == "r"
        if mirrored:
            triangles = mirror_triangles(triangles)

        rot = rotations[segment]
        pos = positions[segment]
        flat: list[float] = []
        for tri in triangles:
            for x, y, z in tri:
                # STL metres -> FlyGym millimetres, then into the neutral pose.
                sx, sy, sz = x * MJ_SCALE, y * MJ_SCALE, z * MJ_SCALE
                tx = rot[0][0] * sx + rot[0][1] * sy + rot[0][2] * sz + pos[0]
                ty = rot[1][0] * sx + rot[1][1] * sy + rot[1][2] * sz + pos[1]
                tz = rot[2][0] * sx + rot[2][1] * sy + rot[2][2] * sz + pos[2]
                flat.extend(
                    [round(tx, precision), round(ty, precision), round(tz, precision)]
                )

        total_triangles += len(triangles)
        parts.append(
            {
                "name": segment,
                "parent": parents[segment],
                "source_mesh": mesh_name,
                "mirrored": mirrored,
                "color": colors[segment]["hex"],
                "material": {
                    "visual_set": colors[segment]["visual_set"],
                    "rgba": colors[segment]["rgba"],
                    "specular": colors[segment]["specular"],
                    "shininess": colors[segment]["shininess"],
                    "opacity": colors[segment]["opacity"],
                },
                "local_position": [
                    round(float(v), precision) for v in rigging[segment]["pos"]
                ],
                "local_quat_wxyz": [
                    round(float(v), 6) for v in rigging[segment]["quat"]
                ],
                "neutral_position": [round(float(v), precision) for v in pos],
                "neutral_quat_wxyz": [
                    round(float(v), 6) for v in matrix_to_quat_wxyz(rot)
                ],
                "triangle_count": len(triangles),
                "positions": flat,
            }
        )

    bboxes = {p["name"]: _part_bbox(p["positions"]) for p in parts}
    scene = {
        "format": "aspa.flygym.fly-scene",
        "format_version": 1,
        "name": "NeuroMechFly simplified (assembled, neutral pose)",
        "units": "mm",
        "up_axis": UP_AXIS,
        "forward_axis": FORWARD_AXIS,
        "left_axis": LEFT_AXIS,
        "position_layout": "flattened_triangle_list",
        "vertex_stride": 3,
        "right_side_mirrored": True,
        "mesh_resolution": Path(MESH_DIR).name,
        "part_count": len(parts),
        "triangle_count": total_triangles,
        "parts": parts,
        "bounds": {
            "min": [
                round(min(b[0][axis] for b in bboxes.values()), precision)
                for axis in range(3)
            ],
            "max": [
                round(max(b[1][axis] for b in bboxes.values()), precision)
                for axis in range(3)
            ],
        },
    }
    return scene, stl_cache


def _part_bbox(
    positions: Sequence[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = positions[0::3]
    ys = positions[1::3]
    zs = positions[2::3]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------
def build_provenance(
    git: GitRepo,
    commit: str,
    scene: dict[str, Any],
    stl_cache: dict[str, bytes],
    pose_order: Sequence[str],
) -> dict[str, Any]:
    """Record exact upstream blobs (git SHA-1 + SHA-256) for every input."""
    config_paths = [LICENSE_PATH, RIGGING_PATH, VISUALS_PATH]
    pose_paths = sorted(
        p
        for p in git.list_tree("HEAD")
        if p.startswith(f"{MODEL_DIR}/pose/neutral/") and p.endswith(".yaml")
    )
    mesh_paths = sorted(stl_cache)

    config_entries = []
    for path in [*config_paths, *pose_paths]:
        blob = git.show(path)
        config_entries.append(
            {
                "path": path,
                "git_sha1": git.blob_sha1(path),
                "sha256": sha256_hex(blob),
                "bytes": len(blob),
            }
        )

    mesh_entries = []
    for path in mesh_paths:
        blob = stl_cache[path]
        mesh_entries.append(
            {
                "path": path,
                "git_sha1": git.blob_sha1(path),
                "sha256": sha256_hex(blob),
                "bytes": len(blob),
            }
        )

    license_text = git.text(LICENSE_PATH)
    return {
        "format": "aspa.provenance",
        "format_version": 1,
        "generated_by": "export_fly.py",
        "generated_utc": _utc_now(),
        "upstream": {
            "project": "NeLy-EPFL/flygym",
            "url": "https://github.com/NeLy-EPFL/flygym",
            "commit": commit,
            "expected_commit": EXPECTED_COMMIT,
            "commit_matches_pin": commit == EXPECTED_COMMIT,
            "model": "NeuroMechFly (simplified_max2000faces)",
            "organism": "Drosophila melanogaster, adult female (micro-CT derived)",
            "read_method": "git show HEAD:<path> (raw bytes; worktree is sparse-excluded)",
        },
        "license": {
            "spdx": "Apache-2.0",
            "file": LICENSE_PATH,
            "git_sha1": git.blob_sha1(LICENSE_PATH),
            "sha256": sha256_hex(license_text.encode("utf-8")),
            "copyright": "Copyright 2023-2026 The NeuroMechFly v2 Authors",
            "covers_meshes": True,
            "note": (
                "The 39 STL meshes live inside the Apache-2.0 repository and are "
                "not carved out by any separate notice. The separately downloaded "
                "fullsize FlyBody meshes are NOT used here."
            ),
        },
        "configs": config_entries,
        "reference_sources": [
            {
                "path": "src/flygym/anatomy.py",
                "role": (
                    "ALL_CONNECTED_SEGMENT_PAIRS, LEG_LINKS/ANTENNA_LINKS/"
                    "PROBOSCIS_LINKS/ABDOMEN_LINKS, RotationAxis (pitch->+Y, "
                    "roll->+Z, yaw->+X), JointPreset.ALL_BIOLOGICAL"
                ),
                "git_sha1": git.blob_sha1("src/flygym/anatomy.py"),
            },
            {
                "path": "src/flygym/compose/fly/base_fly.py",
                "role": (
                    "SCALE=1000 (mm), right-side axis negation, body pos/quat "
                    "composition, visuals fnmatch matching"
                ),
                "git_sha1": git.blob_sha1("src/flygym/compose/fly/base_fly.py"),
            },
            {
                "path": "src/flygym/compose/fly/neuromechfly.py",
                "role": (
                    "mesh mirroring: scale=(SCALE, +/-SCALE, SCALE) and "
                    "mirror_left2right mesh-name mapping"
                ),
                "git_sha1": git.blob_sha1("src/flygym/compose/fly/neuromechfly.py"),
            },
            {
                "path": "src/flygym/compose/pose.py",
                "role": "KinematicPose left->right angle mirroring",
                "git_sha1": git.blob_sha1("src/flygym/compose/pose.py"),
            },
        ],
        "meshes": {
            "directory": MESH_DIR,
            "count": len(mesh_entries),
            "max_faces": MAX_FACES,
            "entries": mesh_entries,
        },
        "pose": {
            "file_used": f"{MODEL_DIR}/pose/neutral/{PREFERRED_POSE}.yaml",
            "axis_order": list(pose_order),
            "axis_order_note": (
                "FlyGym's preferred tutorial order. The neutral pose is "
                "axis-order dependent: thigh pitch is large, so PITCH-last "
                "orders cancel less of the femur/tibia fold. The six bundled "
                "neutral files differ by up to ~0.09 mm per body."
            ),
        },
        "derivation": {
            "scale_metres_to_mm": MJ_SCALE,
            "root_segment": ROOT_SEGMENT,
            "right_side": "mirror left STL with scale=(1000,-1000,1000), winding reversed",
            "right_side_angle_signs": {"pitch": 1, "roll": -1, "yaw": -1},
            "triangle_source": "binary little-endian STL, facet vertex records",
            "validation": scene.get("validation", {}),
        },
        "limitations": [
            "Static neutral pose only; no skinning weights or per-joint animation rig.",
            "Right-side meshes are geometric mirrors of the left STL, not separately scanned.",
            "simplified_max2000faces meshes are decimated (per-part Hausdorff distance "
            "recorded in simplification_metadata.csv); not the full-resolution scan.",
            "Vertex transforms are derived from rigging.yaml + neutral pose + "
            "anatomy.py joint presets, reimplemented in pure Python; they are not "
            "produced by compiling the MuJoCo model.",
            "No external downloads: the lazily fetched fullsize meshes and FlyBody "
            "OBJ meshes are deliberately excluded.",
            ">=2000-face parts are capped by the upstream simplification; antennae and "
            "tarsi are low-poly approximations.",
        ],
    }


def _utc_now() -> str:
    import datetime

    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None:
        ts = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    else:
        ts = datetime.datetime.now(datetime.timezone.utc)
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate(
    rigging: dict[str, dict[str, Any]],
    traversal: Sequence[str],
    positions: dict[str, list[float]],
    scene: dict[str, Any],
) -> dict[str, Any]:
    """Structural self-checks that must hold for the scene to be trustworthy."""
    problems: list[str] = []

    rigging_keys = set(rigging)
    traversal_keys = set(traversal)
    if rigging_keys != traversal_keys:
        problems.append(
            f"rigging/traversal mismatch: only-rigging="
            f"{sorted(rigging_keys - traversal_keys)}, "
            f"only-traversal={sorted(traversal_keys - rigging_keys)}"
        )

    # Left/right symmetry: every right-side position must be the Y-mirror of
    # its left counterpart.
    symmetry_error = 0.0
    for segment in traversal:
        if segment[0] != "r":
            continue
        left = "l" + segment[1:]
        if left not in positions:
            problems.append(f"missing left counterpart for {segment}")
            continue
        mirrored = [positions[left][0], -positions[left][1], positions[left][2]]
        delta = max(abs(a - b) for a, b in zip(positions[segment], mirrored))
        symmetry_error = max(symmetry_error, delta)
    if symmetry_error > 1e-6:
        problems.append(f"left/right symmetry error {symmetry_error:.6f} mm")

    # Legs must be posed, not straight vertical.
    vertical_legs = []
    for leg in LEGS:
        coxa = positions[f"{leg}_coxa"]
        tarsus5 = positions[f"{leg}_tarsus5"]
        # horizontal travel of the tarsus tip relative to the coxa
        horizontal = math.hypot(
            tarsus5[0] - coxa[0], tarsus5[1] - coxa[1]
        )
        drop = coxa[2] - tarsus5[2]
        if horizontal < 0.3 * max(drop, 1e-9) or horizontal < 0.25:
            vertical_legs.append(leg)
    if vertical_legs:
        problems.append(f"legs look straight/vertical: {vertical_legs}")

    if len(traversal) != len(set(traversal)):
        problems.append("duplicate segment in traversal order")

    return {
        "ok": not problems,
        "problem_count": len(problems),
        "problems": problems,
        "segment_count": len(traversal),
        "max_symmetry_error_mm": round(symmetry_error, 9),
        "leg_tip_horizontal_travel_mm": {
            leg: round(
                math.hypot(
                    positions[f"{leg}_tarsus5"][0] - positions[f"{leg}_coxa"][0],
                    positions[f"{leg}_tarsus5"][1] - positions[f"{leg}_coxa"][1],
                ),
                3,
            )
            for leg in LEGS
        },
        "scene_bounds_mm": scene["bounds"],
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="pinned flygym checkout")
    parser.add_argument("--commit", default=EXPECTED_COMMIT, help="expected commit")
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parents[1] / "public/assets/simulator"), help="output directory"
    )
    parser.add_argument(
        "--precision", type=int, default=4, help="decimal places for coordinates (mm)"
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    git = GitRepo(args.repo)
    commit = git.rev_parse("HEAD")
    if commit != args.commit:
        print(
            f"error: checkout HEAD is {commit}, expected {args.commit}",
            file=sys.stderr,
        )
        return 2

    rigging = load_rigging(git)
    visuals = load_visuals(git)
    pose_order, joint_angles = load_pose(git, PREFERRED_POSE)

    pairs = connected_segment_pairs()
    children = build_children(pairs)
    traversal = traversal_order(children)
    parents = build_parents(pairs)

    mesh_files = [
        p
        for p in git.list_tree("HEAD", MESH_DIR)
        if p.endswith(".stl")
    ]
    if len(mesh_files) != 39:
        print(
            f"error: expected 39 bundled STL meshes, found {len(mesh_files)}",
            file=sys.stderr,
        )
        return 3

    if set(rigging) != set(traversal):
        print(
            "error: rigging.yaml segments do not match the reconstructed anatomy",
            file=sys.stderr,
        )
        missing = sorted(set(rigging) - set(traversal))
        extra = sorted(set(traversal) - set(rigging))
        print(f"  only in rigging: {missing}", file=sys.stderr)
        print(f"  only in anatomy: {extra}", file=sys.stderr)
        return 4

    colors = resolve_colors(traversal, visuals)
    positions, rotations = forward_kinematics(
        rigging, pose_order, joint_angles, parents, traversal
    )
    scene, stl_cache = assemble_scene(
        git, rigging, colors, positions, rotations, traversal, parents, args.precision
    )
    scene["validation"] = validate(rigging, traversal, positions, scene)
    if not scene["validation"]["ok"]:
        print("error: validation failed", file=sys.stderr)
        for problem in scene["validation"]["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 5

    provenance = build_provenance(git, commit, scene, stl_cache, pose_order)

    fly_path = out_dir / "fly.json"
    prov_path = out_dir / "provenance.json"
    fly_path.write_text(json.dumps(scene, separators=(",", ":")), encoding="utf-8")
    prov_path.write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )

    print(f"commit           : {commit}")
    print(f"parts            : {scene['part_count']}")
    print(f"triangles        : {scene['triangle_count']}")
    print(f"bounds (mm)      : {scene['bounds']['min']} .. {scene['bounds']['max']}")
    print(f"fly.json         : {fly_path} ({fly_path.stat().st_size} bytes)")
    print(f"provenance.json  : {prov_path} ({prov_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
