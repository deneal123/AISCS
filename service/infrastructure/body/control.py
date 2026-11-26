"""The controller that turns joint targets into muscle recruitment.

Two loops, both of them explicit:

  * a joint loop, a PD on every driven joint, expressed through the muscle pair
    that crosses it: the flexor gets the positive half of the drive, the extensor
    the negative half;
  * a height loop, which is what actually makes the animal stand.  The passive body
    with no muscle tone sinks 0.4 mm, a sixth of its standing height, because the
    joint springs in the source model are far too soft to carry 0.966 dyne.  The
    height loop adds extension to every leg in proportion to how far the body has
    sunk, which is the same thing a real insect does with its leg sense organs.

The height loop is a posture reflex of the twin, not a property of the connectome.
It is labelled here so that no measurement claims the connectome produced it.
"""

from __future__ import annotations

import math

# Gains, all in the twin units.  They were chosen by the sweep in
# .work/twin/strength.py: below kp 20 the body sinks, above kp 100 the muscles
# chatter against the 1 ms control period.
KP = 40.0
KD = 2.0
TONE = 0.06
HEIGHT_GAIN = 6.0
HEIGHT_LIMIT = 0.35


class Posture:
    """Joint-space controller with a height reflex."""

    def __init__(self, body, *, kp=KP, kd=KD, tone=TONE, height_gain=HEIGHT_GAIN):
        self.body = body
        self.kp = float(kp)
        self.kd = float(kd)
        self.tone = float(tone)
        self.height_gain = float(height_gain)
        self.joints = []
        for name in body.muscles.order:
            joint = body.muscles.muscles[name].joint
            if joint not in self.joints:
                self.joints.append(joint)
        self.leg_joints = [j for j in self.joints if "abdomen" not in j]
        self.targets = {}
        self.rest_height = None

    def capture_pose(self):
        """Take the current pose as the target and remember the standing height."""
        self.targets = {j: float(self.body.data.qpos[self.body.qpos_index[j]])
                        for j in self.joints if j in self.body.qpos_index}
        self.rest_height = float(self.body.data.qpos[2])
        return dict(self.targets)

    def set_targets(self, targets):
        for joint, value in targets.items():
            if joint in self.body.qpos_index:
                self.targets[joint] = float(value)

    def height_error(self):
        if self.rest_height is None:
            return 0.0
        return self.rest_height - float(self.body.data.qpos[2])

    def commands(self):
        """Recruitment for every muscle for the current state."""
        out = {name: 0.0 for name in self.body.muscles.order}
        # The height loop must work in BOTH directions.  An earlier version only
        # extended the legs when the body had sunk (max(0, ...)), so a body that rose
        # was never brought back: measured in .work/twin/valbody.py, a walking fly
        # climbed from 0.006 cm to 4.87 cm in three seconds.  A negative drive flexes
        # the legs and is what keeps the animal on the ground.
        extension = max(-HEIGHT_LIMIT, min(HEIGHT_LIMIT,
                                          self.height_gain * self.height_error()))
        for joint in self.joints:
            pair = self.body.muscles.by_joint(joint)
            if len(pair) != 2:
                continue
            angle = float(self.body.data.qpos[self.body.qpos_index[joint]])
            rate = float(self.body.data.qvel[self.body.dof_index[joint]])
            target = self.targets.get(joint, angle)
            drive = self.kp * (target - angle) - self.kd * rate
            bias = extension if joint in self.leg_joints else 0.0
            for muscle in pair:
                if muscle.sign > 0:
                    value = self.tone + bias + drive
                else:
                    value = self.tone - drive
                out[muscle.name] = min(1.0, max(0.0, value))
        return out

    def step(self, dt_s=0.001):
        self.body.set_commands(self.commands())
        return self.body.step(dt_s)

