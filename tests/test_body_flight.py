"""The wings: a beat the connectome commands, and a lift that leaves the ground."""

import math

import numpy as np

from service.infrastructure.body import flight
from service.infrastructure.body.experiment import run_episode
from service.infrastructure.body.loop import BehaviourLoop
from service.infrastructure.body.twin import TwinBody

WING_JOINTS = ("wing_yaw_left", "wing_roll_left", "wing_pitch_left",
               "wing_yaw_right", "wing_roll_right", "wing_pitch_right",
               "haltere_left", "haltere_right")


class _Graph:
    ids = np.arange(8, dtype=np.int64)


def test_the_beat_supports_the_body():
    """A hovering fly must make more lift than it weighs, or it does not hover."""
    ratio = flight.lift_to_weight()
    assert 1.0 < ratio < 2.5, ratio


def test_neither_term_alone_is_enough():
    """Translation and rotation are both needed, which is why both are in the model."""
    translational, _ = flight.quasi_steady_force()
    rotational = flight.rotational_force()
    total = translational + rotational
    assert translational < flight.BODY_WEIGHT_DYNE, translational
    assert rotational < flight.BODY_WEIGHT_DYNE, rotational
    assert rotational / total > 0.25, rotational / total


def test_lift_rises_with_stroke_and_a_weak_beat_cannot_lift():
    ratios = [flight.lift_to_weight(amplitude_rad=math.radians(degrees))
              for degrees in (10, 20, 40, 70)]
    assert ratios == sorted(ratios), ratios
    assert ratios[0] < 0.2, ratios
    assert flight.lift_to_weight(amplitude_rad=math.radians(20)) < 1.0


def test_recruitment_sets_both_frequency_and_amplitude():
    programme = flight.FlightProgram().still()
    assert programme.force()["lift_to_weight"] == 0.0
    weak = programme.commanded_by(0.25).force()["lift_to_weight"]
    strong = programme.commanded_by(1.0).force()["lift_to_weight"]
    assert weak < strong, (weak, strong)
    assert strong > 1.0 > weak


def test_every_wing_joint_is_antagonised_and_mapped():
    body = TwinBody()
    for joint in WING_JOINTS:
        assert joint in body.joint_index, joint
        pair = body.muscles.by_joint(joint)
        signs = sorted(muscle.sign for muscle in pair)
        assert signs == [-1, 1], (joint, signs)
    wing_cells = {int(n) for name, ids in body.mapping.items()
                  if name.startswith(("wing_", "haltere_")) for n in ids}
    assert len(wing_cells) >= 20, len(wing_cells)


def test_the_wing_reaches_a_real_stroke_at_two_hundred_hertz():
    """The shipped servo gear gave 27 degrees; a fly beats 140 degrees peak to peak."""
    body = TwinBody()
    body.reset()
    joint = "wing_yaw_left"
    qi = body.qpos_index[joint]
    names = [muscle.name for muscle in body.muscles.by_joint(joint)]
    extensor = body.actuator_index[[n for n in names if n.endswith("_extensor")][0]]
    flexor = body.actuator_index[[n for n in names if n.endswith("_flexor")][0]]
    trace = []
    dt = 0.0001
    for step in range(int(0.25 / dt)):
        s = math.sin(2.0 * math.pi * 200.0 * step * dt)
        body.data.ctrl[:] = 0.0
        body.data.ctrl[extensor] = max(0.0, s)
        body.data.ctrl[flexor] = max(0.0, -s)
        body.mujoco.mj_step(body.model, body.data)
        trace.append(float(body.data.qpos[qi]))
    stroke_deg = math.degrees(max(trace[-500:]) - min(trace[-500:]))
    assert stroke_deg > 60.0, stroke_deg


def test_flight_leaves_the_ground_and_walking_does_not():
    record, _ = run_episode(_Graph(), source_cells=None, current_na=0.0,
                            site_um=(400, 380, 360), duration_ms=80,
                            flight_recruitment=1.0)
    body = record.record()["body"]
    assert body["flight"]["beating"] is True
    assert body["flight"]["airborne_cm"] > 0.5, body["flight"]
    assert "flight" in record.record()["labels"]
    standing, _ = run_episode(_Graph(), source_cells=None, current_na=0.0,
                              site_um=(400, 380, 360), duration_ms=40)
    assert standing.record()["body"]["flight"]["beating"] is False
    assert "flight" not in standing.record()["labels"]
    assert abs(standing.record()["body"]["flight"]["airborne_cm"]) < 0.2


def test_a_burst_on_wing_motor_neurons_starts_the_beat():
    body = TwinBody()
    loop = BehaviourLoop(body)
    loop.settle()
    cells = sorted(loop.wing_neurons)
    assert cells
    table = {cell: 6 for cell in cells[:4]}
    height0 = float(body.data.qpos[2])
    for tick in range(80):
        loop.advance(0.001, table if tick == 10 else None)
    assert loop.flight_latency_ms is not None
    assert loop.flight.amplitude_rad > 0.0
    assert float(body.data.qpos[2]) - height0 > 0.02