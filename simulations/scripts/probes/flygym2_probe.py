"""Exercise the pinned FlyGym 2 CPU body and original locomotion controller."""

import csv
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import imageio.v3 as iio
import matplotlib
import mujoco
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flygym.anatomy import BodySegment
from flygym.compose import ActuatorType
from flygym.compose.physics import ContactParams
from flygym.compose.world import FlatGroundWorld
from flygym.simulation import Simulation
from flygym.utils.math import Rotation3D
from flygym_demo.complex_terrain.common import (
    apply_locomotion_action,
    make_locomotion_fly,
)
from flygym_demo.complex_terrain.cpg_controller import (
    CPGController,
    make_tripod_cpg_network,
)
from flygym_demo.complex_terrain.preprogrammed import PreprogrammedSteps

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
DT = 0.0001


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_sim(friction=1.0):
    fly = make_locomotion_fly()
    fly.add_tracking_camera()
    world = FlatGroundWorld()
    world.add_fly(
        fly,
        spawn_position=[0, 0, 0.2],
        spawn_rotation=Rotation3D("quat", [1, 0, 0, 0]),
        ground_contact_params=ContactParams(sliding_friction=friction),
    )
    sim = Simulation(world, timestep=DT)
    sim.reset()
    mujoco.mj_forward(sim.mj_model, sim.mj_data)
    return fly, sim


def trial(
    fly, sim, seed, name, seconds=3.0, render=False, adhesion=True, amplitude=1.0
):
    started = time.perf_counter()
    sim.reset()
    mujoco.mj_forward(sim.mj_model, sim.mj_data)
    initial = sim.mj_data.qpos.copy()
    steps = PreprogrammedSteps()
    cpg = make_tripod_cpg_network(DT, seed=seed, intrinsic_amplitude=amplitude)
    controller = CPGController(cpg, steps)
    camera = fly.cameraname_to_mjcfcamera["trackcam"].name
    renderer = None
    if render:
        renderer = sim.set_renderer(
            camera, camera_res=(480, 640), playback_speed=1, output_fps=25
        )
    thorax = fly.get_bodysegs_order().index(BodySegment("c_thorax"))
    records = {
        key: []
        for key in (
            "time",
            "qpos",
            "qvel",
            "joint_angles",
            "body_positions",
            "actuator_forces",
            "contacts",
            "cpg_phases",
            "cpg_magnitudes",
            "command",
            "adhesion_command",
        )
    }
    for step in range(round(seconds / DT)):
        action = controller.step()
        if not adhesion:
            sim.set_leg_adhesion_states(fly.name, np.zeros(6, dtype=bool))
            sim.set_actuator_inputs(
                fly.name, ActuatorType.POSITION, action.joint_angles
            )
        else:
            apply_locomotion_action(sim, fly.name, action)
        assert action.joint_angles.shape == (42,)
        assert np.isfinite(action.joint_angles).all()
        sim.step()
        assert np.isfinite(sim.mj_data.qpos).all()
        assert np.isfinite(sim.mj_data.qvel).all()
        if renderer is not None:
            sim.render_as_needed()
        if step % 100 == 99:
            fields = {
                "time": sim.mj_data.time,
                "qpos": sim.mj_data.qpos.copy(),
                "qvel": sim.mj_data.qvel.copy(),
                "joint_angles": sim.get_joint_angles(fly.name).copy(),
                "body_positions": sim.get_body_positions(fly.name).copy(),
                "actuator_forces": sim.get_actuator_forces(
                    fly.name, ActuatorType.POSITION
                ).copy(),
                "contacts": sim.get_ground_contact_info(fly.name)[0].copy(),
                "cpg_phases": cpg.curr_phases.copy(),
                "cpg_magnitudes": cpg.curr_magnitudes.copy(),
                "command": action.joint_angles.copy(),
                "adhesion_command": (
                    action.adhesion_onoff.copy()
                    if adhesion
                    else np.zeros(6, dtype=bool)
                ),
            }
            for key, value in fields.items():
                records[key].append(value)
    arrays = {key: np.asarray(value) for key, value in records.items()}
    assert all(np.isfinite(value).all() for value in arrays.values())
    arrays["initial_qpos"] = initial
    arrays["thorax_xyz"] = arrays["body_positions"][:, thorax, :]
    path = OUT / (name + ".npz")
    np.savez_compressed(path, **arrays)
    with (OUT / (name + ".csv")).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["time_s", "thorax_x_mm", "thorax_y_mm", "thorax_z_mm", "contact_legs"]
        )
        for t, pos, contact in zip(
            arrays["time"], arrays["thorax_xyz"], arrays["contacts"]
        ):
            writer.writerow([float(t), *pos.tolist(), int((contact > 0).sum())])
    frames = []
    if renderer is not None:
        frames = renderer.frames[camera]
        assert len(frames) >= 70
        assert frames[0].shape == (480, 640, 3)
        renderer.save_video(OUT / "locomotion-seed-1.mp4")
        iio.imwrite(OUT / "body-start.png", frames[0])
        iio.imwrite(OUT / "body-finish.png", frames[-1])
        renderer.close()
        sim.renderer = None
    result = {
        "name": name,
        "seed": seed,
        "duration_s": seconds,
        "timestep_s": DT,
        "steps": round(seconds / DT),
        "samples": len(arrays["time"]),
        "seconds": time.perf_counter() - started,
        "sha256": sha(path),
        "finite": True,
        "shapes": {key: list(value.shape) for key, value in arrays.items()},
        "displacement_mm": float(
            np.linalg.norm(arrays["thorax_xyz"][-1, :2] - arrays["thorax_xyz"][0, :2])
        ),
        "minimum_thorax_z_mm": float(arrays["thorax_xyz"][:, 2].min()),
        "frames": len(frames),
        "adhesion": adhesion,
        "cpg_amplitude": amplitude,
    }
    print(json.dumps(result), flush=True)
    return result, arrays


def main():
    fly, sim = make_sim()
    results, baseline = [], None
    command_hashes = []
    for index, seed in enumerate((1, 2, 3, 1)):
        result, arrays = trial(
            fly, sim, seed, f"run-{index}-seed-{seed}", render=index == 0
        )
        results.append(result)
        command_hashes.append(hashlib.sha256(arrays["command"].tobytes()).hexdigest())
        if index == 0:
            baseline = arrays
        if index == 3:
            assert all(np.array_equal(arrays[key], baseline[key]) for key in arrays)
    variants = []
    for name, kwargs in (
        ("adhesion-off", {"adhesion": False}),
        ("cpg-amplitude-zero", {"amplitude": 0.0}),
    ):
        row, _ = trial(fly, sim, 1, name, seconds=0.5, **kwargs)
        variants.append(row)
    other_fly, other_sim = make_sim(friction=0.4)
    row, _ = trial(other_fly, other_sim, 1, "friction-0-4", seconds=0.5)
    variants.append(row)
    repeat_equal = all(np.array_equal(arrays[key], baseline[key]) for key in arrays)
    assert repeat_equal
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), layout="constrained")
    for index, seed in enumerate((1, 2, 3)):
        data = np.load(OUT / f"run-{index}-seed-{seed}.npz")
        xyz = data["thorax_xyz"]
        axes[0].plot(xyz[:, 0], xyz[:, 1], label=f"seed {seed}")
        axes[1].plot(data["time"], xyz[:, 2], label=f"seed {seed}")
    axes[0].set(
        xlabel="Thorax x (mm)", ylabel="Thorax y (mm)", title="Recorded trajectories"
    )
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].legend()
    axes[1].set(
        xlabel="Time (s)", ylabel="Thorax z (mm)", title="Height above flat ground"
    )
    axes[2].plot(baseline["time"], baseline["command"][:, :7])
    axes[2].set(
        xlabel="Time (s)",
        ylabel="Command angle (rad)",
        title="First leg: 7 position commands",
    )
    fig.suptitle(
        "SIM-020 | FlyGym 2.1 CPU body, author CPG; no connectome or ECAP model"
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("body-recordings." + suffix), dpi=160)
    plt.close(fig)
    report = {
        "status": "passed",
        "scope": "CPU NeuroMechFly body, flat ground, author CPG controller",
        "biological_validation": False,
        "connectome": False,
        "ecap": False,
        "same_seed_after_reset_exact": repeat_equal,
        "different_seed_commands": len(set(command_hashes[:3])) == 3,
        "runs": results,
        "variants": variants,
        "model": {
            "nq": sim.mj_model.nq,
            "nv": sim.mj_model.nv,
            "nu": sim.mj_model.nu,
            "nbody": sim.mj_model.nbody,
        },
        "units": {
            "time": "s",
            "length": "mm",
            "joint_angle": "rad",
            "cpg_phase": "rad",
            "actuator_forces": "raw MuJoCo model units; no SI conversion asserted",
        },
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("flygym", "mujoco", "numpy", "scipy", "imageio")
        },
    }
    (OUT / "functional.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
