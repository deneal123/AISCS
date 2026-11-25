"""Walking, defined where it matters: in foot space.

A gait written as joint angles waves the legs. A gait written as foot positions walks:
the stance foot has to stay where it was put while the body travels over it, and the
swing foot has to come back to the front through the air. This module states both
requirements as foot trajectories and lets the inverse kinematics of the twin turn
them into joint targets.

Two details decide whether the animal actually goes anywhere, and both were measured
before they were written down here:

  * the reference frame travels with the body. A gait whose foot targets are fixed in
    the world runs out of leg after one step and then only drags: measured in
    .work/twin/follow1.py, the body moved 0.62 mm in 2 s with a fixed frame and 8.95 mm
    with a travelling one;
  * a stance foot is anchored where it touched down, not led along a path. Driving the
    planted claw along a trajectory wins against friction, because the joint servo is
    stronger than the contact: measured in .work/twin/reach.py, the claw followed its
    IK goal to within 0.0004 cm while the body stood still. Anchored stance with a
    clamp of 0.8 mm gave 10.6 mm/s in .work/twin/speed3.py, against 0.06 mm/s before.

The gait is open loop. It is a prescription for the legs, not a claim that the
connectome produced it. What the connectome produces is the escape, which is where
the measurements in the nociception series live.

Units are the twin units: centimetre, radian, second.
"""

from __future__ import annotations

import math

import numpy as np

from .kinematics import LEGS, LegKinematics

# Tripod gait: these three legs swing together, the other three carry the body.
TRIPOD_A = ("T1_left", "T2_right", "T3_left")
TRIPOD_B = ("T1_right", "T2_left", "T3_right")
GAIT_PERIOD_S = 0.18
SWING_FRACTION = 0.4
# Stroke: how far the foot travels fore and aft, cm.  A fly step is about 0.4 mm.
STROKE_CM = 0.22
# Lift: how high the claw rises during swing, cm.  It has to clear the tarsus and
# the tibia as well as the floor, which is why it is not a hair.
LIFT_CM = 0.02
# Sideways sway of the swing foot, cm: a fly does not swing its feet in a straight
# line, and without the sway the claw drags the tarsus chain.
SWAY_CM = 0.004
# How far a stance claw may be pulled from the point where it landed, cm.  The leg
# cannot hold an arbitrarily long displacement, and a claw that is pulled too far
# pops free and skates: 0.08 cm holds, larger values do not.
STANCE_CLAMP_CM = 0.08
# How far below its rest height a stance foot is aimed, cm.  Zero is enough once the
# stance foot is anchored; a positive press is what makes the claw bite on a smooth
# floor and is kept as a knob for floors that need it.
STANCE_PRESS_CM = 0.0

# Escape: the measured defensive response.  The abdomen curls, the legs extend, the
# animal moves away from where the noxious stimulus landed, and it does so faster
# than it walks when undisturbed.
ESCAPE_DURATION_S = 0.35
ESCAPE_ONSET_S = 0.012
ESCAPE_CURL_RAD = 0.10
ESCAPE_STRIDE_SCALE = 2.0

def _phase_of(leg, phase, period_s):
    shift = 0.0 if leg in TRIPOD_A else 0.5
    return (phase + shift) % 1.0


class FootGait:
    """A tripod gait expressed as foot positions, converted to joint targets by IK."""

    def __init__(self, body, *, period_s=GAIT_PERIOD_S, stroke_cm=STROKE_CM,
                 lift_cm=LIFT_CM, sway_cm=SWAY_CM, press_cm=STANCE_PRESS_CM,
                 clamp_cm=STANCE_CLAMP_CM):
        self.body = body
        self.kinematics = LegKinematics(body)
        self.period_s = float(period_s)
        self.stroke_cm = float(stroke_cm)
        self.lift_cm = float(lift_cm)
        self.sway_cm = float(sway_cm)
        self.press_cm = float(press_cm)
        self.clamp_cm = float(clamp_cm)
        self.phase = 0.0
        self.rest = {}
        self.base_height = None
        # The frame the foot targets are expressed in.  It travels with the body, so
        # the legs never run out of reach; see the module docstring.
        self.origin_x = 0.0
        # Where each stance claw touched down, in world coordinates.
        self.anchors = {}
        self.targets = {}
        self.errors = {}

    def capture(self):
        """Record where the claws stand now; that pose is the gait reference."""
        self.rest = {leg: self.kinematics.foot(leg).copy() for leg in LEGS}
        self.base_height = float(self.body.data.qpos[2])
        self.origin_x = float(self.body.data.qpos[0])
        self.anchors = {}
        return dict(self.rest)

    def travel_cm(self):
        """How far the body has gone since the reference was captured."""
        return float(self.body.data.qpos[0]) - self.origin_x

    def advance(self, dt_s, *, stride_scale=1.0):
        self.phase = (self.phase + dt_s / self.period_s) % 1.0
        return self.phase

    def foot_target(self, leg, phase=None, *, stride_scale=1.0):
        """Where this leg foot must be at this phase, in world coordinates."""
        if phase is None:
            phase = self.phase
        if not self.rest:
            self.capture()
        rest = self.rest[leg]
        travel = self.travel_cm()
        local = _phase_of(leg, phase, self.period_s)
        stroke = self.stroke_cm * stride_scale
        if local < SWING_FRACTION:
            self.anchors.pop(leg, None)
            progress = local / SWING_FRACTION
            # In the air: the foot comes back to the front, lifted in an arc.  The
            # reference travels with the body, so the foot lands ahead of it.
            fore = rest[0] + travel + stroke * (-0.5 + progress)
            up = self.lift_cm * math.sin(math.pi * progress)
            side = rest[1] + self.sway_cm * math.sin(2.0 * math.pi * progress)
            return np.array([fore, side, rest[2] + up])
        # On the ground: the claw stays where it landed.  Its goal is that point,
        # clamped so the leg is never pulled past what it can hold.
        if leg not in self.anchors:
            self.anchors[leg] = self.kinematics.foot(leg).copy()
        anchor = self.anchors[leg]
        here = self.kinematics.foot(leg)
        fore = here[0] + max(-self.clamp_cm, min(self.clamp_cm, anchor[0] - here[0]))
        return np.array([fore, rest[1], anchor[2] - self.press_cm])

    def joint_targets(self, *, phase=None, stride_scale=1.0):
        """Joint angles that place every foot on its trajectory."""
        out = {}
        self.errors = {}
        for leg in LEGS:
            target = self.foot_target(leg, phase, stride_scale=stride_scale)
            angles, error = self.kinematics.solve(leg, target)
            self.errors[leg] = error
            for name, value in zip(self.kinematics.joints[leg], angles):
                out[name] = float(value)
        self.targets = out
        return out

    def step(self, posture, dt_s=0.001, *, stride_scale=1.0):
        """Advance the phase and hand the posture controller its new targets."""
        self.advance(dt_s, stride_scale=stride_scale)
        posture.set_targets(self.joint_targets(stride_scale=stride_scale))
        return posture.step(dt_s)


class Escape:
    """The defensive response, driven by whatever the connectome decided."""

    def __init__(self, duration_s=ESCAPE_DURATION_S):
        self.duration_s = float(duration_s)
        self.elapsed = None
        self.side = 0.0

    @property
    def active(self):
        return self.elapsed is not None and self.elapsed < self.duration_s

    def trigger(self, *, side=0.0, delay_s=ESCAPE_ONSET_S):
        self.elapsed = -float(delay_s)
        self.side = float(side)

    def advance(self, dt_s):
        if self.elapsed is not None:
            self.elapsed += dt_s
            if self.elapsed >= self.duration_s:
                self.elapsed = None

    def envelope(self):
        """Response strength in [0, 1]: fast onset, slower relaxation."""
        if self.elapsed is None or self.elapsed < 0:
            return 0.0
        progress = self.elapsed / self.duration_s
        rise = min(1.0, progress / 0.15)
        fall = 1.0 if progress < 0.5 else max(0.0, 1.0 - (progress - 0.5) / 0.5)
        return rise * fall

    def joint_targets(self, joints):
        """Abdominal curl, as joint angles the posture loop can aim at.

        The escape is expressed in joint space rather than in muscle space because
        the posture loop already owns recruitment: adding muscle commands here would
        drive the same muscle twice through two different gain scales.
        """
        amount = self.envelope()
        if amount <= 0.0:
            return {}
        out = {}
        for joint in joints:
            if not joint.startswith("abdomen") or "abduct" in joint:
                continue
            out[joint] = -amount * ESCAPE_CURL_RAD
        if self.side != 0.0:
            direction = 1.0 if self.side > 0 else -1.0
            for joint in joints:
                if joint.startswith("abdomen") and "abduct" in joint:
                    out[joint] = direction * amount * ESCAPE_CURL_RAD * 0.5
        return out

    def stride_scale(self):
        """How much faster than a walk the escape is."""
        return 1.0 + (ESCAPE_STRIDE_SCALE - 1.0) * self.envelope()


def blend(gait_targets, escaped_targets):
    """Combine the gait and the escape; the escape wins where they overlap."""
    out = dict(gait_targets)
    for joint, value in escaped_targets.items():
        out[joint] = value
    return out