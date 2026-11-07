#!/usr/bin/env python3
"""Export the complete pinned FlyBody hinge hierarchy and MuJoCo reference poses.

The baked scene mesh stays immutable. This exports kinematics, not a muscle
controller or a predicted animal trajectory. All positions are millimetres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np

SCENE_SHA = "8eb70a265a179e811c902fda4334aa83bc34f54a58d400db0c3a6f98ccbd62dd"
XML_SHA = "35541d5312f71e7c96156c345cd90918867513a2b3dafbb07b8684ee59b6f4dc"


def matrix(rotation, position):
    value = np.eye(4)
    value[:3, :3] = np.asarray(rotation).reshape(3, 3)
    value[:3, 3] = np.asarray(position) * 10
    return value.reshape(-1).tolist()


def export(xml_path: Path, asset_root: Path, target: Path, references: Path):
    if mujoco.__version__ != "3.3.7":
        raise ValueError("Use the pinned MuJoCo 3.3.7")
    if hashlib.sha256(xml_path.read_bytes()).hexdigest() != XML_SHA:
        raise ValueError("Unregistered XML; read the immutable SIM Git source")
    scene_bytes = (asset_root / "scene.json").read_bytes()
    if hashlib.sha256(scene_bytes).hexdigest() != SCENE_SHA:
        raise ValueError("Unregistered baked scene")
    asset = json.loads(scene_bytes)
    if (
        hashlib.sha256((asset_root / "scene.bin").read_bytes()).hexdigest()
        != asset["binary"]["sha256"]
    ):
        raise ValueError("Baked mesh integrity failure")
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    for joint in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
        if name.startswith("wing_"):
            address = model.jnt_qposadr[joint]
            data.qpos[address] = model.qpos_spring[address]
    mujoco.mj_forward(model, data)
    rest = data.qpos.copy()
    bodies, joints = [], []
    for body in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body)
        rotation = np.empty(9)
        mujoco.mju_quat2Mat(rotation, model.body_quat[body])
        joint_names, free_root = [], False
        start, count = int(model.body_jntadr[body]), int(model.body_jntnum[body])
        for joint in range(start, start + count):
            kind = model.jnt_type[joint]
            if kind == mujoco.mjtJoint.mjJNT_FREE:
                free_root = True
                continue
            if kind != mujoco.mjtJoint.mjJNT_HINGE:
                raise ValueError("Unsupported source joint")
            joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
            address = int(model.jnt_qposadr[joint])
            joint_names.append(joint_name)
            joints.append(
                {
                    "name": joint_name,
                    "body": name,
                    "axis": model.jnt_axis[joint].tolist(),
                    "position_mm": (model.jnt_pos[joint] * 10).tolist(),
                    "reference_rad": float(model.qpos0[address]),
                    "rest_rad": float(rest[address]),
                    "limited": bool(model.jnt_limited[joint]),
                    "range_rad": model.jnt_range[joint].tolist(),
                }
            )
        bodies.append(
            {
                "name": name,
                "parent": int(model.body_parentid[body]) if body else None,
                "base_local": matrix(rotation, model.body_pos[body]),
                "rest_world": matrix(data.xmat[body], data.xpos[body]),
                "free_root": free_root,
                "joints": joint_names,
            }
        )
    names = {body["name"] for body in bodies}
    if any(part["body_name"] not in names for part in asset["parts"]):
        raise ValueError("Mesh part without a source body")
    manifest = {
        "format": "aspa.flybody.kinematics",
        "version": 1,
        "mesh_asset_sha256": SCENE_SHA,
        "source_xml_sha256": XML_SHA,
        "source_commit": "fdbbd866b203a709a164970b0a8996108edd57a5",
        "upstream_commit": "f3b6013629c7b94f8ee93fd977b161fa8350f9bc",
        "license": "Apache-2.0",
        "mujoco": mujoco.__version__,
        "units": {"position": "mm", "angle": "rad"},
        "matrix_layout": "row-major 4x4; column-vector transform",
        "free_root_policy": "fixed to the registered rest pose",
        "source_joints": model.njnt,
        "hinge_joints": len(joints),
        "bodies": bodies,
        "joints": joints,
        "parts": {part["name"]: part["body_name"] for part in asset["parts"]},
        "limitations": [
            "Forward kinematics only; no inferred muscle forces or motor-neuron mapping.",
            "The eyes follow their head body; no independent eye joint exists here.",
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n"
    )
    cases = []
    samples = [("neutral", {})]
    samples.append(("head-three-axes", {"head_abduct": 0.11, "head_twist": -0.16, "head": 0.08}))
    for seed in (1, 2, 3):
        rng = np.random.default_rng(seed)
        pose = {}
        for joint in joints:
            value = joint["rest_rad"] + rng.uniform(-0.07, 0.07)
            if joint["limited"]:
                value = np.clip(value, *joint["range_rad"])
            pose[joint["name"]] = float(value)
        samples.append((f"all-joints-seed-{seed}", pose))
    for name, pose in samples:
        data.qpos[:] = rest
        for joint_name, angle in pose.items():
            joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            data.qpos[model.jnt_qposadr[joint]] = angle
        mujoco.mj_forward(model, data)
        cases.append(
            {
                "name": name,
                "angles_rad": pose,
                "world": {
                    body["name"]: matrix(data.xmat[i], data.xpos[i])
                    for i, body in enumerate(bodies)
                },
                "anchors_mm": {
                    joint["name"]: (
                        data.xanchor[
                            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint["name"])
                        ]
                        * 10
                    ).tolist()
                    for joint in joints
                },
            }
        )
    references.parent.mkdir(parents=True, exist_ok=True)
    references.write_text(
        json.dumps(
            {
                "scope": "MuJoCo 3.3.7 kinematic references; not recorded animal movements",
                "rig_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "source_xml_sha256": XML_SHA,
                "cases": cases,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "bodies": len(bodies),
        "joints": len(joints),
        "parts": len(manifest["parts"]),
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-xml", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.source_xml, args.asset_root, args.output, args.references)))
