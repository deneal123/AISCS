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
# Step period, s, and stroke, cm.  These two set the walking speed, and the speed is
# the one thing about the gait that can be checked against a real animal: Mendes et
# al. 2013 (eLife 2:e00231) measured freely walking wild-type flies at 7.2 to
# 44.7 mm/s, most often 28 mm/s, with a step period near 60 ms above 30 mm/s.  The
# twin used to walk at 10.8 mm/s with a 180 ms period, which is at the bottom edge
# of the real range and three times slower than a fly steps.
#
# Measured sweep through the real control loop (.work/twin/gc5.log, gc6.log, 2 s
# each, standing gait only, no stimulus):
#   period 0.18, stroke 0.22 -> 12.0 mm/s, IK 0.040, height span 0.042
#   period 0.12, stroke 0.22 -> 12.9 mm/s, IK 0.038, height span 0.024
#   period 0.09, stroke 0.22 -> 19.1 mm/s, IK 0.036, height span 0.018
#   period 0.09, stroke 0.26 -> 19.5 mm/s, IK 0.064, height span 0.028
#   period 0.09, stroke 0.32 -> blows up, IK 7.99: the claw is pulled past its clamp
#   period 0.075, stroke 0.26 -> 16.0 mm/s: faster steps walk FURTHER but slip more
# A duty factor of 0.5 (swing 0.5) did not help at any period: 15.5 mm/s at 0.09
# against 19.5 at 0.4, because a longer swing leaves the tripod short of support.
#
# So 0.09 s and 0.26 cm is the fastest gait that still stands, and it lands at
# 19.5 mm/s: inside the real range, still below the most-represented 28 mm/s.  The
# ceiling is the stance clamp, not the stride - stroke 0.32 tears the claws loose
# rather than pushing the body - so getting to 28 mm/s needs a slipping contact
# model, not another constant.
GAIT_PERIOD_S = 0.09
SWING_FRACTION = 0.4
STROKE_CM = 0.26
# Lift: how high the claw rises during swing, cm.  It has to clear the tarsus and
# the tibia as well as the floor, which is why it is not a hair.  0.01 cm walks
# slightly faster and steadier than 0.02 at every period measured above (13.2 mm/s
# against 11.4 at period 0.12), because a lower swing keeps the body from rocking.
LIFT_CM = 0.01
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
# The escape is faster, but not arbitrarily faster.  Above 1.8 the phase runs so far
# ahead of the tripods that a leg is still in the air when its tripod is asked to carry
# again and the animal spins: measured in .work/twin/escape_boundary.py, the 350 ms
# heading change stays between 0.2 and 4.0 degrees up to a stride of 1.8 and becomes
# -129 degrees at 2.0, while the displacement at 1.6 is already 1.54 times a walk
# (0.512 against 0.332 cm).
ESCAPE_STRIDE_SCALE = 1.6

# How fast the animal turns at full steering, radian per second: a 350 ms escape is
# about 35 degrees, the order of a measured fly turn.
#
# The turn is prescribed, and that is a limitation of this model, not a shortcut.  A
# turning fly twists its body against the claws that are on the floor; here every stance
# claw is clamped to a fixed world point, so the twist is absorbed as slip instead of
# turning anything.  Measured in .work/twin/tw1.log with the moment applied on every
# substep: 0.002 to 0.04 dyne cm leaves the heading at 3-4 degrees whichever way the
# animal is told to turn, which is exactly what an escape with no steering does, and
# 0.08 and above tears the feet loose and throws the animal into the air (height
# 0.77 cm).  There is no value at which the claws turn the body.  So the heading is
# prescribed, and the body and the whole foot set are rotated together rigidly, which
# leaves the step geometry untouched.  A slip limit on the claws instead of a hard clamp
# is the change that would make the turn physical; that is not done here.
TURN_RATE_RAD_S = 1.75

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
        self.origin = np.zeros(2)
        # Heading of the frame, radian.  It follows the body every control period, so a
        # turned animal steps along the way it is actually facing rather than along world
        # x, and the stance clamp pulls it fore and aft instead of sideways.
        self.heading = 0.0
        # Where each stance claw touched down, in world coordinates.
        self.anchors = {}
        self.targets = {}
        self.errors = {}

    def capture(self):
        """Record where the claws stand now; that pose is the gait reference."""
        self.origin = np.array([float(self.body.data.qpos[0]),
                                float(self.body.data.qpos[1])])
        self.heading = self.body_yaw()
        # Reference feet as offsets from the frame origin, never as world points: every
        # target this module plans is a point of the frame, and mixing the two puts the
        # swing a body's width off.
        self.rest = {}
        for leg in LEGS:
            foot = self.kinematics.foot(leg)
            fore, side = self.frame_of(foot[0], foot[1])
            self.rest[leg] = np.array([fore, side, float(foot[2])])
        self.base_height = float(self.body.data.qpos[2])
        self.anchors = {}
        return dict(self.rest)

    def body_yaw(self):
        """Heading of the body about the vertical axis, radian, from its quaternion."""
        w, x, y, z = [float(value) for value in self.body.data.qpos[3:7]]
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    def axes(self):
        """The frame's forward and left axes in world coordinates."""
        cos, sin = math.cos(self.heading), math.sin(self.heading)
        return cos, sin

    def frame_of(self, x, y):
        """A world point as (fore, side) offsets from the frame origin."""
        cos, sin, = self.axes()
        dx = float(x) - float(self.origin[0])
        dy = float(y) - float(self.origin[1])
        return dx * cos + dy * sin, -dx * sin + dy * cos

    def world_of(self, fore, side):
        """A (fore, side) offset from the frame origin, in world coordinates."""
        cos, sin = self.axes()
        x = float(self.origin[0]) + fore * cos - side * sin
        y = float(self.origin[1]) + fore * sin + side * cos
        return x, y

    def follow_body(self):
        """Take the frame's heading from the body.

        Not called by advance(): see the note there on why reading the heading back turns
        the steering into a feedback loop.  It is here for callers that want to resync the
        frame after something else has turned the animal.
        """
        self.heading = self.body_yaw()
        return self.heading

    def travel_cm(self):
        """How far the body has gone forward since the reference was captured.

        Measured along the frame's own axis: once the animal has turned, a world-x
        difference would count sideways motion as progress.
        """
        cos, sin = self.axes()
        dx = float(self.body.data.qpos[0]) - float(self.origin[0])
        dy = float(self.body.data.qpos[1]) - float(self.origin[1])
        return dx * cos + dy * sin

    def steer(self, angle_rad):
        """Turn the animal, and every foot target with it, about its own body.

        The body, the reference feet and the stance anchors all go round by the same
        angle about the same centre, so the step pattern is carried round rigidly and the
        legs see exactly the geometry they saw before the turn.  Turning only part of the
        set is what broke the walk in every earlier attempt: the anchors stayed in the
        old heading while the reference feet moved, and each tripod was pulled two ways
        at once (measured in .work/twin/tn4.log through tn12.log, and in .work/twin/fd4.log
        where a reference that moved twice as fast as the body spun the animal 111
        degrees in 400 ms).
        """
        angle = float(angle_rad)
        if not angle:
            return 0.0
        centre_x = float(self.body.data.qpos[0])
        centre_y = float(self.body.data.qpos[1])
        cos, sin = math.cos(angle), math.sin(angle)
        # The reference feet are frame offsets, so they are invariant under a rotation of
        # the frame: the whole set goes round with the animal by construction.  Only the
        # frame origin has to be carried round the body, or the reference stops describing
        # the feet that are actually under it.
        self._rotate_about(self.origin, centre_x, centre_y, cos, sin)
        # The anchors are world points, and a claw nailed to the floor would lever the
        # animal into the air when the body turns over it (measured in .work/twin/fz1.log,
        # height 0.53 cm on a right escape).  Dropping them makes the next stance sample
        # re-take the claw where the leg now stands, which is what a real foot does.
        self.anchors.clear()
        self.heading = math.atan2(math.sin(self.heading + angle),
                                  math.cos(self.heading + angle))
        self.body.rotate_heading(angle)
        return angle

    @staticmethod
    def _rotate_about(point, centre_x, centre_y, cos, sin):
        """Turn a world point round a vertical axis through (centre_x, centre_y)."""
        dx, dy = float(point[0]) - centre_x, float(point[1]) - centre_y
        point[0] = centre_x + dx * cos - dy * sin
        point[1] = centre_y + dx * sin + dy * cos

    def rebase(self, window_cm=0.20):
        """Move the reference forward when the body has outwalked it.

        The reference frame travels with the body but is only re-captured when the
        caller asks, so a long walk eventually aims every foot target behind the
        animal and the legs run out of reach. Rebasing keeps the foot targets inside
        one stroke of where the feet actually are; the anchors are dropped because
        they were expressed against the old reference and are re-taken on the next
        stance sample. The window is a whole number of strokes on purpose: a partial
        stroke would make one step shorter than the others and show up as a limp.
        """
        travel = self.travel_cm()
        if abs(travel) < float(window_cm):
            return 0.0
        # Continuity, not re-capture, and only the origin moves.  A target is
        # origin + rest[0] + travel and travel is measured FROM the origin, so advancing
        # the origin by the travel lowers travel by the same amount and leaves every
        # target exactly where it was.  Adding the travel to the reference as well moves
        # each target twice as fast as the body and tears the tripod apart: measured in
        # .work/twin/fd4.log, a plain walk spun 111 degrees in 400 ms that way.
        cos, sin = self.axes()
        self.origin[0] += travel * cos
        self.origin[1] += travel * sin
        # Anchors are world points, not offsets from the reference, so they survive the
        # move untouched: the stance branch aims at anchors[leg][0] directly and never
        # consults rest. Dropping them here would re-plant a standing foot mid-step,
        # which is what the gait test caught.
        return travel

    def advance(self, dt_s, *, stride_scale=1.0, turn=0.0):
        """Advance the step cycle; a stride scale shortens the cycle, not just the step.

        Scaling only the stroke length leaves the animal stepping at the same rate and
        the escape does not speed it up: measured in .work/twin/ep3.log, an episode
        that triggered the escape covered 0.558 mm in 120 ms against 0.541 mm without
        one, a difference of three per cent. A fly that escapes takes faster steps, so
        the scale multiplies the phase rate as well as the stroke.
        """
        # The frame heading is NOT read back from the body every period.  Doing that makes
        # the steering a feedback loop -- a little yaw rotates the frame, the rotated frame
        # pushes a little more yaw -- and a plain walk drifts: measured in .work/twin/fz4.log,
        # 9.1 degrees in 400 ms and 28.5 in 1500.  The heading changes only when the gait is
        # steered, so with no steering the frame is the world frame and the walk is exactly
        # the walk that was measured before the turn existed.
        self.phase = (self.phase + dt_s * float(stride_scale) / self.period_s) % 1.0
        if turn:
            self.steer(dt_s * TURN_RATE_RAD_S * float(turn))
        return self.phase

    def foot_target(self, leg, phase=None, *, stride_scale=1.0, turn=0.0):
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
            x, y = self.world_of(fore, side)
            return np.array([x, y, rest[2] + up])
        # On the ground: the claw stays where it landed.  Its goal is that point, clamped
        # along the frame's forward axis so the leg is never pulled past what it can hold.
        # The clamp runs along that axis and not along world x, or a turned animal is held
        # back sideways instead of fore and aft.
        if leg not in self.anchors:
            self.anchors[leg] = self.kinematics.foot(leg).copy()
        anchor = self.anchors[leg]
        here = self.kinematics.foot(leg)
        here_fore, here_side = self.frame_of(here[0], here[1])
        anchor_fore, _ = self.frame_of(anchor[0], anchor[1])
        fore = here_fore + max(-self.clamp_cm, min(self.clamp_cm, anchor_fore - here_fore))
        # The across-frame coordinate is the nominal stance width, not the foot's own
        # lateral position: a stance that follows the foot sideways holds nothing and the
        # animal slides away from where it is standing.
        x, y = self.world_of(fore, rest[1])
        return np.array([x, y, anchor[2] - self.press_cm])

    def joint_targets(self, *, phase=None, stride_scale=1.0, turn=0.0):
        """Joint angles that place every foot on its trajectory."""
        out = {}
        self.errors = {}
        for leg in LEGS:
            target = self.foot_target(leg, phase, stride_scale=stride_scale, turn=turn)
            angles, error = self.kinematics.solve(leg, target)
            self.errors[leg] = error
            for name, value in zip(self.kinematics.joints[leg], angles):
                out[name] = float(value)
        self.targets = out
        return out

    def step(self, posture, dt_s=0.001, *, stride_scale=1.0, turn=0.0):
        """Advance the phase and hand the posture controller its new targets."""
        self.advance(dt_s, stride_scale=stride_scale, turn=turn)
        posture.set_targets(self.joint_targets(stride_scale=stride_scale, turn=turn))
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

    def turn(self):
        """Signed steering for the gait; the animal turns away from the stimulus side.

        The sign is the one the abdomen already uses: a negative side is a stimulus on
        the right and the animal turns left, away from it.  Before this existed, an
        escape with a side of +1 and one with -1 both drifted the same 2.2 degrees as no
        escape at all (measured in .work/twin/turning.py).
        """
        amount = self.envelope()
        if amount <= 0.0 or self.side == 0.0:
            return 0.0
        return -amount if self.side > 0.0 else amount


def blend(gait_targets, escaped_targets):
    """Combine the gait and the escape; the escape wins where they overlap."""
    out = dict(gait_targets)
    for joint, value in escaped_targets.items():
        out[joint] = value
    return out