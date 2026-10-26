"""Exercise the pinned legacy Gymnasium API and author hybrid controller."""

import csv
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import imageio.v3 as iio
import imageio_ffmpeg
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flygym_gymnasium import Camera, Fly
from flygym_gymnasium.arena import FlatTerrain, MixedTerrain
from flygym_gymnasium.examples.locomotion import HybridTurningController
from flygym_gymnasium.preprogrammed import default_leg_sensor_placements

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
DT = 0.0001


def build(arena=None, render=False):
    fly = Fly(
        enable_adhesion=True,
        contact_sensor_placements=default_leg_sensor_placements,
    )
    cameras = []
    if render:
        cameras = [
            Camera(
                fly.model.worldbody,
                "camera_left",
                fly.name,
                play_speed=1,
                fps=25,
                play_speed_text=False,
            )
        ]
    return HybridTurningController(
        fly=fly,
        cameras=cameras,
        timestep=DT,
        seed=1,
        arena=arena if arena is not None else FlatTerrain(),
    )


def trial(sim, seed, name, duration=1.0, drive=(1.0, 1.0), render=False):
    started = time.perf_counter()
    sim.reset(seed=seed)
    initial_qpos = sim.physics.data.qpos.copy()
    records = {
        key: []
        for key in (
            "time",
            "qpos",
            "qvel",
            "fly",
            "joints",
            "contact_forces",
            "end_effectors",
            "cpg_phases",
            "cpg_magnitudes",
            "drive",
        )
    }
    terminated_count = 0
    for step in range(round(duration / DT)):
        action = np.asarray(drive, dtype=float)
        obs, _reward, terminated, truncated, _info = sim.step(action)
        terminated_count += int(terminated or truncated)
        assert np.isfinite(sim.physics.data.qpos).all()
        assert np.isfinite(sim.physics.data.qvel).all()
        if render:
            sim.render()
        if step % 100 == 99:
            fields = {
                "time": sim.curr_time,
                "qpos": sim.physics.data.qpos.copy(),
                "qvel": sim.physics.data.qvel.copy(),
                "cpg_phases": sim.cpg_network.curr_phases.copy(),
                "cpg_magnitudes": sim.cpg_network.curr_magnitudes.copy(),
                "drive": action,
                **{
                    key: np.asarray(obs[key]).copy()
                    for key in ("fly", "joints", "contact_forces", "end_effectors")
                },
            }
            for key, value in fields.items():
                records[key].append(value)
    arrays = {key: np.asarray(value) for key, value in records.items()}
    assert all(np.isfinite(value).all() for value in arrays.values())
    arrays["initial_qpos"] = initial_qpos
    np.savez_compressed(OUT / (name + ".npz"), **arrays)
    with (OUT / (name + ".csv")).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "thorax_x_mm", "thorax_y_mm", "thorax_z_mm"])
        for t, fly in zip(arrays["time"], arrays["fly"]):
            writer.writerow([float(t), *fly[0].tolist()])
    video_check = None
    if render:
        camera = sim.cameras[0]
        assert len(camera._frames) >= 24
        path = OUT / "hybrid-walk-seed-1.mp4"
        camera.save_video(path, stabilization_time=0)
        iio.imwrite(OUT / "body-start.png", camera._frames[0])
        iio.imwrite(OUT / "body-finish.png", camera._frames[-1])
        decoder = imageio_ffmpeg.read_frames(str(path), output_params=["-threads", "1"])
        meta = next(decoder)
        count = 0
        for frame in decoder:
            assert len(frame) == 640 * 480 * 3
            count += 1
        assert count == len(camera._frames)
        video_check = {
            "frames": count,
            "fps": meta["fps"],
            "size": meta["size"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    result = {
        "name": name,
        "seed": seed,
        "duration_s": duration,
        "steps": round(duration / DT),
        "seconds": time.perf_counter() - started,
        "finite": True,
        "termination_flags": terminated_count,
        "shapes": {key: list(value.shape) for key, value in arrays.items()},
        "video": video_check,
        "displacement_mm": float(
            np.linalg.norm(arrays["fly"][-1, 0, :2] - arrays["fly"][0, 0, :2])
        ),
        "sha256": hashlib.sha256((OUT / (name + ".npz")).read_bytes()).hexdigest(),
    }
    print(json.dumps(result), flush=True)
    return result, arrays


def main():
    sim = build(render=True)
    rows, first, same = [], None, False
    phase_hashes = []
    for i, seed in enumerate((1, 2, 3, 1)):
        row, data = trial(sim, seed, f"run-{i}-seed-{seed}", render=i == 0)
        rows.append(row)
        phase_hashes.append(hashlib.sha256(data["cpg_phases"].tobytes()).hexdigest())
        if i == 0:
            first = data
        if i == 3:
            same = all(np.array_equal(data[key], first[key]) for key in data)
    variants = []
    for name, drive in (
        ("left-drive", (1.2, 0.4)),
        ("right-drive", (0.4, 1.2)),
        ("zero-drive", (0.0, 0.0)),
    ):
        row, _ = trial(sim, 1, name, duration=0.25, drive=drive)
        variants.append(row)
    sim.close()
    terrain = build(arena=MixedTerrain())
    row, _ = trial(terrain, 1, "mixed-terrain", duration=0.25)
    variants.append(row)
    terrain.close()
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), layout="constrained")
    for i, seed in enumerate((1, 2, 3)):
        data = np.load(OUT / f"run-{i}-seed-{seed}.npz")
        xyz = data["fly"][:, 0]
        axes[0].plot(xyz[:, 0], xyz[:, 1], label=f"seed {seed}")
        axes[1].plot(data["time"], xyz[:, 2], label=f"seed {seed}")
    axes[0].set(
        xlabel="Thorax x (mm)", ylabel="Thorax y (mm)", title="Recorded trajectories"
    )
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].legend()
    axes[1].set(xlabel="Time (s)", ylabel="Thorax z (mm)", title="Body height")
    axes[2].plot(first["time"], first["joints"][:, 0, :7])
    axes[2].set(
        xlabel="Time (s)",
        ylabel="Joint angle (rad)",
        title="First leg: observed joint angles",
    )
    fig.suptitle(
        "SIM-021 | Legacy FlyGym Gymnasium, hybrid controller; not a connectome or ECAP model"
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("hybrid-recordings." + suffix), dpi=160)
    plt.close(fig)
    report = {
        "status": "passed" if same else "partial",
        "repeat_equal": same,
        "scope": "CPU body, author hybrid locomotion controller, flat/mixed terrain",
        "different_seed_cpg_states": len(set(phase_hashes[:3])) == 3,
        "runs": rows,
        "variants": variants,
        "versions": {
            key: importlib.metadata.version(key)
            for key in (
                "flygym-gymnasium",
                "gymnasium",
                "mujoco",
                "dm_control",
                "numpy",
                "numba",
            )
        },
        "units": {
            "time": "s",
            "body_position": "mm",
            "joint_angle": "rad",
            "contact_forces": "raw model units; no SI conversion asserted",
        },
        "biological_validation": False,
        "connectome": False,
        "ecap": False,
    }
    (OUT / "functional.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    assert same, "Native reset did not reproduce the same seed; raw arrays retained"


if __name__ == "__main__":
    main()
