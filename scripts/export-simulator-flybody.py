#!/usr/bin/env python3
"""Export the Apache-2.0 FlyBody used by SIM-003, without copying its app code.

Requires mujoco==3.3.7 and numpy. Reads the pinned SIM Git objects only. The
upstream Menagerie XML and license are checked against their pinned hashes.
All intermediate files belong in the caller's ignored --work directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.request import urlopen

import mujoco
import numpy as np

SIM_COMMIT = "fdbbd866b203a709a164970b0a8996108edd57a5"
UPSTREAM_COMMIT = "f3b6013629c7b94f8ee93fd977b161fa8350f9bc"
UPSTREAM = f"https://raw.githubusercontent.com/google-deepmind/mujoco_menagerie/{UPSTREAM_COMMIT}/flybody/"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def export(repo: Path, out: Path, work: Path) -> dict:
    if mujoco.__version__ != "3.3.7":
        raise ValueError("Use the pinned MuJoCo 3.3.7 exporter")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if commit != SIM_COMMIT:
        raise ValueError("SIM-003 commit differs from the evaluated version")
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", "web/model/assets", "web/model/fruitfly.xml"], cwd=repo, text=True
    ).splitlines()
    inputs = []
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        content = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=repo)
        target = work / Path(name).relative_to("web/model")
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_bytes(content)
        inputs.append({"path": name, "sha256": digest(content), "bytes": len(content)})
    primary_xml = urlopen(UPSTREAM + "fruitfly.xml", timeout=45).read()
    if primary_xml != (work / "fruitfly.xml").read_bytes():
        raise ValueError("SIM model XML differs from the Apache-2.0 primary model")
    license_bytes = urlopen(UPSTREAM + "LICENSE", timeout=45).read()
    (out / "LICENSE-FlyBody.txt").write_bytes(license_bytes)
    model = mujoco.MjModel.from_xml_path(str(work / "fruitfly.xml"))
    data = mujoco.MjData(model)
    # The source's zero pose spreads the wings. Use its own passive spring
    # resting angles for those six joints; do not invent an animation policy.
    wing_pose = {}
    for joint in range(model.njnt):
        joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
        if joint_name and joint_name.startswith("wing_"):
            address = model.jnt_qposadr[joint]
            data.qpos[address] = model.qpos_spring[address]
            wing_pose[joint_name] = float(data.qpos[address])
    mujoco.mj_forward(model, data)
    parts, buffers = [], []
    offset = 0

    def append(array: np.ndarray) -> dict:
        nonlocal offset
        payload = array.tobytes(order="C")
        descriptor = {"byte_offset": offset, "count": int(array.size)}
        buffers.append(payload)
        offset += len(payload)
        return descriptor

    bounds = []
    for geom in range(model.ngeom):
        if model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_MESH or model.geom_group[geom] > 2:
            continue
        rgba = model.geom_rgba[geom].copy()
        material = model.geom_matid[geom]
        if material >= 0 and np.array_equal(rgba, [.5, .5, .5, 1]):
            rgba = model.mat_rgba[material].copy()
        if rgba[3] == 0:
            continue
        mesh = model.geom_dataid[geom]
        vertex_start, face_start, face_count = model.mesh_vertadr[mesh], model.mesh_faceadr[mesh], model.mesh_facenum[mesh]
        faces = model.mesh_face[face_start:face_start + face_count]
        normal_faces = model.mesh_facenormal[face_start:face_start + face_count]
        source_positions = model.mesh_vert[vertex_start + faces].reshape(-1, 3)
        source_normals = model.mesh_normal[model.mesh_normaladr[mesh] + normal_faces].reshape(-1, 3)
        rotation = data.geom_xmat[geom].reshape(3, 3)
        # FlyBody uses centimetres, +X forward, +Z up. Export millimetres.
        positions = ((source_positions @ rotation.T + data.geom_xpos[geom]) * 10).astype("<f4")
        normals = (source_normals @ rotation.T).astype("<f4")
        if not np.isfinite(positions).all() or not np.isfinite(normals).all():
            raise ValueError("Non-finite exported geometry")
        # Preserve the OBJ's per-corner normals and source face order.
        unique, inverse = np.unique(np.concatenate([positions, normals], axis=1), axis=0, return_inverse=True)
        body = int(model.geom_bodyid[geom])
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom)
        body_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body)
        root = body
        while root and not (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, root) or "").startswith("coxa_"):
            root = int(model.body_parentid[root])
        leg_root = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, root) if root else None
        parts.append({
            "name": name, "body_name": body_name, "leg_root": leg_root,
            "pivot_mm": (data.xpos[root] * 10).tolist() if root else None,
            "rgba": rgba.tolist(), "triangle_count": int(face_count),
            "positions": append(unique[:, :3].astype("<f4")),
            "normals": append(unique[:, 3:].astype("<f4")),
            "indices": append(inverse.astype("<u4")),
        })
        bounds.append((positions.min(axis=0), positions.max(axis=0)))
        if name == "thorax":
            origin = ((positions.min(axis=0).astype(float) + positions.max(axis=0).astype(float)) / 2).tolist()
            thorax_faces = int(face_count)
    binary = b"".join(buffers)
    (out / "scene.bin").write_bytes(binary)
    asset = {
        "format": "aspa.flybody.fly-scene", "format_version": 1, "units": "mm",
        "name": "FlyBody from SIM-003 / MuJoCo Menagerie", "part_count": len(parts),
        "triangle_count": sum(part["triangle_count"] for part in parts),
        "binary": {"file": "scene.bin", "sha256": digest(binary), "bytes": len(binary)},
        "parts": parts, "origin_mm": origin,
        "bounds": {"min": np.min([b[0] for b in bounds], axis=0).tolist(), "max": np.max([b[1] for b in bounds], axis=0).tolist()},
    }
    write_json(out / "scene.json", asset)
    registration = {
        "mesh_asset_id": "flybody-sim003-fdbbd866-rest-v1",
        "mesh_sha256": digest((out / "scene.json").read_bytes()), "source_commit": SIM_COMMIT,
        "region_id": "thoracic-local-v1", "mesh_part": "thorax", "mesh_triangle_count": thorax_faces,
        "origin_mm": origin, "mesh_units": "mm", "model_units": "um", "um_to_mm": .001,
        "bridge_kind": "author-defined rigid embedding, not a reconstructed neural mapping",
        "attachment": "body-attached-static-v1", "contact_shape": "ideal-point",
        "operator_version": "lfpy-pointsource-e1-minus-ref-v1",
    }
    write_json(out / "registration.json", registration)
    provenance = {
        "asset_id": registration["mesh_asset_id"], "source": "https://github.com/cnqso/infinite-sugar",
        "source_commit": SIM_COMMIT, "primary": "https://github.com/google-deepmind/mujoco_menagerie/tree/" + UPSTREAM_COMMIT + "/flybody",
        "primary_commit": UPSTREAM_COMMIT, "primary_xml_identical": True,
        "license": "Apache-2.0", "license_sha256": digest(license_bytes), "inputs": inputs,
        "exporter": {"mujoco": mujoco.__version__, "numpy": np.__version__, "units_cm_to_mm": 10},
        "modifications": "MuJoCo neutral body pose with source wing spring resting angles; rigid transforms and cm-to-mm conversion; float32 indexed buffers. No mesh subdivision or source application code.",
        "wing_resting_angles_rad": wing_pose,
        "joint_count": int(model.njnt), "hinge_dofs": int(model.nv - 6),
        "part_count": len(parts), "triangle_count": asset["triangle_count"],
        "files": [{"name": name, "sha256": digest((out / name).read_bytes())} for name in ("scene.json", "scene.bin", "registration.json")],
        "limitations": ["Visual body is not a reconstructed neural model", "Body motion controller is not imported or validated"],
    }
    write_json(out / "provenance.json", provenance)
    return {"part_count": len(parts), "triangles": asset["triangle_count"], "binary_bytes": len(binary), "origin_mm": origin}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.repo.resolve(), args.out.resolve(), args.work.resolve())))
