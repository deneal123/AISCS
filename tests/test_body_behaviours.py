"""The behaviours the twin performs, measured through the loop it actually runs."""

from __future__ import annotations

import math

import numpy as np

from service.infrastructure.body import behaviours
from service.infrastructure.body.kinematics import LEGS
from service.infrastructure.body.loop import BehaviourLoop
from service.infrastructure.body.twin import TwinBody


def _yaw(body):
    w, x, y, z = [float(v) for v in body.data.qpos[3:7]]
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _wrap(angle):
    while angle > 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
    return angle


def _run(behaviour, ticks=600):
    body = TwinBody()
    loop = BehaviourLoop(body)
    loop.select(behaviour)
    loop.settle()
    start = np.array([float(body.data.qpos[0]), float(body.data.qpos[1])])
    heading = _yaw(body)
    claws = behaviours.claw_heights(loop.gait)
    for _ in range(ticks):
        loop.advance(0.001)
    end = np.array([float(body.data.qpos[0]), float(body.data.qpos[1])])
    return dict(distance_mm=float(np.linalg.norm(end - start)) * 10.0,
                forward_mm=float((end - start)[0]) * 10.0,
                turn_deg=_wrap(_yaw(body) - heading),
                rise_cm=behaviours.claw_heights(loop.gait), claws=claws,
                loop=loop, body=body)


def test_the_animal_walks_forward_by_default():
    out = _run("walk")
    assert out["forward_mm"] > 3.0, out
    assert abs(out["turn_deg"]) < 5.0, out


def test_the_animal_backs_up_when_it_is_told_to():
    out = _run("back")
    assert out["forward_mm"] < -3.0, out
    # Reversing the phase as well as the stroke yaws 16.5 degrees in 600 ms; the
    # stroke-only reversal keeps the animal facing where it started.
    assert abs(out["turn_deg"]) < 5.0, out


def test_a_turn_in_place_pivots_without_travelling():
    out = _run("turn_in_place")
    assert out["turn_deg"] < -20.0, out
    assert out["distance_mm"] < 2.0, out


def test_the_turn_can_go_either_way():
    left = _run(behaviours.turn_in_place(direction=1.0))
    right = _run(behaviours.turn_in_place(direction=-1.0))
    assert left["turn_deg"] > 20.0, left
    assert right["turn_deg"] < -20.0, right


def test_grooming_lifts_the_front_claws_and_leaves_the_hind_pair_down():
    out = _run("groom")
    rise = out["rise_cm"]
    base = out["claws"]
    front = max(rise["T1_left"] - base["T1_left"], rise["T1_right"] - base["T1_right"])
    hind = max(rise["T3_left"] - base["T3_left"], rise["T3_right"] - base["T3_right"])
    assert front > 0.02, (front, rise)
    assert abs(hind) < 0.01, (hind, rise)
    assert out["distance_mm"] < 1.0, out


def test_a_freeze_stands_still():
    out = _run("freeze")
    assert out["distance_mm"] < 1.0, out
    assert abs(out["turn_deg"]) < 5.0, out


def test_a_hurt_grooming_animal_drops_the_pose_and_runs():
    body = TwinBody()
    loop = BehaviourLoop(body)
    loop.select("groom")
    loop.settle()
    base = behaviours.claw_heights(loop.gait)
    for _ in range(300):
        loop.advance(0.001)
    raised = behaviours.claw_heights(loop.gait)["T1_left"] - base["T1_left"]
    assert raised > 0.02, raised
    position = np.array([float(body.data.qpos[0]), float(body.data.qpos[1])])
    loop.trigger_escape(side=1.0)
    for _ in range(350):
        loop.advance(0.001)
    dropped = behaviours.claw_heights(loop.gait)["T1_left"] - base["T1_left"]
    moved = float(np.linalg.norm(
        np.array([float(body.data.qpos[0]), float(body.data.qpos[1])]) - position)) * 10.0
    assert dropped < 0.01, dropped
    assert moved > 2.0, moved


def test_an_unknown_behaviour_is_refused():
    try:
        behaviours.named("somersault")
    except ValueError as error:
        assert "somersault" in str(error)
    else:
        raise AssertionError("an unknown behaviour was accepted")


def test_a_behaviour_name_selects_the_same_programme_as_the_factory():
    loop_behaviour = BehaviourLoop(TwinBody()).select("back")
    direct = behaviours.back()
    assert loop_behaviour.name == direct.name == "back"
    assert loop_behaviour.stroke_scale == direct.stroke_scale == -1.0


def test_every_behaviour_knows_whether_it_moves():
    assert behaviours.walk().moves()
    assert behaviours.back().moves()
    assert not behaviours.turn_in_place().moves()
    assert not behaviours.groom().moves()
    assert not behaviours.freeze().moves()
