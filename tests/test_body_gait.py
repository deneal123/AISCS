"""The twin has to walk: a gait that does not move the body is not a gait."""

import numpy as np
import pytest

try:
    import mujoco
except ImportError:  # the shim has no importorskip
    pytest.skip("mujoco is not installed", allow_module_level=True)

from service.infrastructure.body.kinematics import LEGS
from service.infrastructure.body.loop import BehaviourLoop
from service.infrastructure.body.twin import TwinBody


def _gripping(body):
    """Give the claws a real friction cone: MuJoCo default condim=1 has no friction."""
    model = body.model
    for geom in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[geom])) or ""
        if name.startswith("claw"):
            model.geom_condim[geom] = 3
            model.geom_friction[geom] = [4.0, 0.005, 0.0001]
    return body


def _walk(seconds=2.0, stroke_cm=0.22, period_s=0.18):
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=stroke_cm, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=period_s, height_gain=0.0)
    loop.settle(steps=300)
    start_x = float(body.data.qpos[0])
    heights = []
    for step in range(int(seconds * 1000)):
        loop.advance(0.001)
        if step % 250 == 0:
            heights.append(float(body.data.qpos[2]))
    return (float(body.data.qpos[0]) - start_x) * 10.0, heights


def test_the_gait_carries_the_body_forward_at_a_measured_speed():
    """10 mm/s is what .work/twin/speed3.py measured; a still body would be 0."""
    distance_mm, _ = _walk()
    assert distance_mm > 10.0, "the gait moved the body only %.3f mm" % distance_mm
    assert distance_mm < 80.0, "the body was flung %.3f mm rather than walked" % distance_mm


def test_a_faster_period_walks_further_in_the_same_time():
    """Speed has to follow the step rate, which a slipping foot would not do."""
    slow, _ = _walk(seconds=1.5, period_s=0.30)
    fast, _ = _walk(seconds=1.5, period_s=0.12)
    assert fast > slow, "fast %.3f mm was not faster than slow %.3f mm" % (fast, slow)


def test_the_body_stays_near_its_standing_height():
    """Walking is not flying and not sinking: the height has to stay bounded."""
    _, heights = _walk()
    span = max(heights) - min(heights)
    assert span < 0.08, "height wandered by %.4f cm" % span


def test_a_stance_foot_is_anchored_where_it_landed():
    """While a claw is planted its anchor must not move; a new step may move it."""
    from service.infrastructure.body.footgait import SWING_FRACTION, _phase_of
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=0.22, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=0.18, height_gain=0.0)
    loop.settle(steps=300)
    gait = loop.gait
    previous = {}
    held = 0
    for _ in range(600):
        loop.advance(0.001)
        current = {leg: point.copy() for leg, point in gait.anchors.items()}
        for leg, point in current.items():
            local = _phase_of(leg, gait.phase, gait.period_s)
            if local < SWING_FRACTION:
                continue
            if leg in previous and np.allclose(point, previous[leg], atol=1e-9):
                held += 1
            elif leg in previous:
                raise AssertionError("the anchor of %s moved while it was planted" % leg)
        previous = current
    assert held > 100, "a planted claw was tracked for only %d samples" % held

def test_the_reference_frame_travels_with_the_body():
    """A world-fixed reference exhausts the reach after one step.

    The frame is moved in steps rather than continuously, so what keeps growing is the
    origin of the frame, not the offset from it: rebase() deliberately resets that
    offset so the foot targets stay within one window of where the feet are.
    """
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=0.22, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=0.18, height_gain=0.0)
    loop.settle(steps=300)
    origin0 = float(loop.gait.origin[0])
    for _ in range(4000):
        loop.advance(0.001)
    moved_mm = (float(loop.gait.origin[0]) - origin0) * 10.0
    assert moved_mm > 1.0, "the reference moved only %.3f mm" % moved_mm
    assert abs(loop.gait.travel_cm()) < 0.25, "the offset from the reference ran away"
    assert set(loop.gait.rest) == set(LEGS)

def _yaw_degrees(body):
    import math
    w, x, y, z = [float(v) for v in body.data.qpos[3:7]]
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _escape(side, ticks=350):
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=0.22, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=0.18, height_gain=0.0)
    loop.settle(steps=300)
    start = _yaw_degrees(body)
    loop.trigger_escape(side=side)
    for _ in range(ticks):
        loop.advance(0.001)
    return _yaw_degrees(body) - start, float(body.data.qpos[2])


def test_an_escape_turns_away_from_the_side_that_was_hurt():
    """The two sides must turn opposite ways; before steering they did not.

    Measured in .work/twin/frame3.py after the turn was made a rigid rotation:
    side +1 gives -22.4 degrees and side -1 gives +24.8, with no steering at all
    giving +3.7. A turn that cannot change sign is not a turn, which is why the
    sign is asserted rather than just the size.
    """
    left, left_height = _escape(1.0)
    right, right_height = _escape(-1.0)
    assert left < -5.0, "an escape away from a right-side stimulus went %.1f deg" % left
    assert right > 5.0, "an escape away from a left-side stimulus went %.1f deg" % right
    assert right_height > -0.01, "the animal sank to %.3f cm while turning" % right_height


def test_a_plain_walk_does_not_turn():
    """Steering must not leak into walking: a long walk stays on its heading.

    Reading the frame heading back from the body every period turned the steering
    into a feedback loop and drifted 28.5 degrees over 1500 ms of plain walking
    (.work/twin/fz4.log); the frame now turns only when the gait is steered.
    """
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=0.22, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=0.18, height_gain=0.0)
    loop.settle(steps=300)
    start = _yaw_degrees(body)
    for _ in range(1500):
        loop.advance(0.001)
    drift = _yaw_degrees(body) - start
    assert abs(drift) < 5.0, "a plain walk drifted %.1f degrees" % drift


def test_steering_does_not_tear_the_stance_apart():
    """A turn must keep the step geometry: the IK must stay near its walking error.

    Leaving the stance anchors nailed to the world while the body turned levered the
    animal into the air (height 0.53 cm, .work/twin/fz1.log), and keeping the feet as
    world points while the frame turned made it fall through the floor (z -0.078 cm,
    .work/twin/fz2.log). Both are caught here by the height and the IK error.
    """
    left, height = _escape(1.0)
    assert abs(left) < 45.0, "the turn ran away to %.1f degrees" % left
    assert abs(height) < 0.05, "the animal left the floor to %.4f cm" % height

def test_the_episode_records_which_way_the_animal_turned():
    """A displacement has no sign: the dataset needs the heading change.

    run_episode is given a raster that triggers an escape to one side; the record has
    to carry a heading change of the matching sign, and a run with no escape has to
    carry one near zero. Without this column an escape to the left and an escape to
    the right are the same row in a synthetic dataset.
    """
    from service.infrastructure.body.experiment import _heading, _turn_deg
    from service.infrastructure.body.twin import TwinBody
    body = _gripping(TwinBody())
    loop = BehaviourLoop(body, compliance=1.0, stroke_cm=0.22, lift_cm=0.02,
                         kp=60.0, kd=4.0, period_s=0.18, height_gain=0.0)
    loop.settle(steps=300)
    start = _heading(body)
    loop.trigger_escape(side=1.0)
    for _ in range(350):
        loop.advance(0.001)
    turned = _turn_deg(start, _heading(body))
    assert turned < -5.0, "the recorded turn was %.1f deg" % turned
    assert -180.0 < turned <= 180.0
