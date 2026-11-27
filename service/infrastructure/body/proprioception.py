"""The body tells the network where it is: proprioception, closing the loop.

Before this module the coupling was one-way. A stimulus reached the connectome, the
connectome reached the muscles, the body moved, and the network never learned that it
had moved: every episode was open loop, and an escape turned into a fall because
nothing reported the ground. That is the largest missing piece of the twin as a
simulator, and it is not a physics problem -- it is a missing wire.

The wire is not invented. The connectome has 964 proprioceptive sensory cells inside
the registered graph, and they are exactly the classes that measure what the body is
doing:

  * 426 campaniform sensilla, 218 entering through ADMN and 195 through DMetaN, which
    sit at the leg joints and measure the strain of the cuticle;
  * 425 chordotonal organs, 193 through MetaLN, 163 through MesoLN, 36 through ProLN,
    33 through ProCN, the stretch receptors of the femur and the joints;
  * 113 hair plates, which measure the angle of the coxa at the body.

THE ENCODING, AND WHY IT IS NOT A PER-CELL RATE CODE. The first version fired each
cell independently, spread over the phase of its own accumulator. That was measured
and it does not work, for a reason worth writing down: a single spike into this graph
delivers a fraction of a millivolt, the kernel gain is 0.075, and one cell firing
alone moves its targets by less than the distance to threshold, so the loop died at
the sensor layer -- 964 driven cells produced 3 downstream spikes, and a bent leg
produced the same 3 (see .work/twin/prop3.py, prop5.py). A joint, in the animal, is
measured by a whole sheet of sensilla that fire together because they sit on the same
piece of cuticle and are deformed by the same movement. Encoding that sheet as a
sheet -- all the cells assigned to one joint firing on the same millisecond -- is both
closer to the anatomy and the only encoding measured to propagate (prop10.py,
prop11.py): at gain 0.15 a still animal recruits 129 downstream cells, a bent front
leg 276, a bent hind leg 338, and the front and hind signatures differ in 151 and 230
cells respectively. At gain 0.075 the same experiment gives 10, 10 and 4.

What is NOT claimed: which campaniform sensillum sits on which leg joint of which
segment is not in the connectome, so the assignment below is a proxy -- cells of a
class are dealt round-robin over the joints of that class -- and every record says so.
"""

from __future__ import annotations

# Which cell classes carry the body state, by the subclass the annotation gives them.
PROPRIOCEPTIVE_CLASSES = ("campaniform sensilla", "chordotonal organ", "hair plate")
# Joint families the twin has, and the class that measures each. A hair plate measures
# the angle at the coxa; a chordotonal organ measures stretch across the femur and the
# tibia; a campaniform sensillum measures strain where the leg meets the body. The three
# are assigned by family rather than to individual cells, because the connectome does
# not resolve the individual cells to legs.
JOINT_CLASSES = (
    ("coxa", "hair plate"),
    ("femur", "chordotonal organ"),
    ("tibia", "chordotonal organ"),
    ("tarsus", "campaniform sensilla"),
)
# The rate a joint fires at when it is at rest, and at full excursion. A chordotonal
# organ of a fly fires from a few Hz to a few hundred; the twin uses 2..40 Hz because its
# control grid is 1 ms and a joint firing every tick would swamp the raster with the body
# instead of the network.
REST_HZ = 2.0
FULL_HZ = 40.0
# A joint has to leave its rest angle by this fraction of its travel before its sensilla
# notice. Without the deadband a standing fly has every sensillum firing at the rest rate
# and a slow walk is indistinguishable from standing.
DEADBAND = 0.02


def joint_class(joint_name):
    """Which sensory class measures this joint, or None if the twin has no sensor for it."""
    for prefix, sensory in JOINT_CLASSES:
        if joint_name.startswith(prefix):
            return sensory
    return None


def assign_cells(cells, joints):
    """Deal the cells of each class round-robin over the joints that class measures.

    The connectome does not say which sensillum sits on which leg, so every joint gets
    an equal share of its class instead of a guess at the anatomy. Recorded as a proxy.
    """
    out = {joint: [] for joint in joints}
    for sensory, ids in cells.items():
        targets = [joint for joint in joints if joint_class(joint) == sensory]
        if not targets:
            continue
        for index, cell in enumerate(sorted(int(v) for v in ids)):
            out[targets[index % len(targets)]].append(int(cell))
    return out


class Proprioception:
    """Drives the proprioceptive cells from the joint angles the body reached.

    The encoder is a rate code with a rest rate, so a standing animal is not silent: a
    real hair plate is not silent either, and a network that only hears the body when it
    moves cannot tell standing from deaf. What a joint rate controls is how often its
    sheet fires; a sheet fires as a sheet.
    """

    def __init__(self, body, cells, *, rest_hz=REST_HZ, full_hz=FULL_HZ,
                 deadband=DEADBAND, gain=1.0):
        self.body = body
        self.rest_hz = float(rest_hz)
        self.full_hz = float(full_hz)
        self.deadband = float(deadband)
        self.gain = float(gain)
        self.classes = {name: sorted(int(v) for v in ids)
                        for name, ids in cells.items() if ids}
        joints = [name for name in self.body.qpos_index
                  if joint_class(name) is not None]
        self.joints = joints
        self.by_joint = assign_cells(self.classes, joints)
        self.rest_angles = {}
        self.rates = {joint: self.rest_hz for joint in joints}
        self.phase = {joint: (index * 0.37) % 1.0
                      for index, joint in enumerate(joints)}
        self.capture()
        self.spikes = 0
        self.fired = {}
        self.sheets = 0

    def capture(self):
        """Take the standing pose as the rest angle of every joint."""
        self.rest_angles = {name: float(self.body.data.qpos[self.body.qpos_index[name]])
                            for name in self.joints}
        return dict(self.rest_angles)

    def limits(self, joint):
        """Travel of a joint from the model, used to normalise its displacement."""
        index = self.body.joint_index.get(joint)
        if index is None:
            return 1.0
        low, high = self.body.model.jnt_range[index]
        span = float(high) - float(low)
        return span if span > 1e-6 else 1.0

    def angle_error(self, joint):
        value = float(self.body.data.qpos[self.body.qpos_index[joint]])
        rest = self.rest_angles.get(joint, value)
        return (value - rest) / self.limits(joint)

    def rates_now(self):
        """Firing rate per joint, Hz, from the current pose."""
        out = {}
        for joint in self.joints:
            error = abs(self.angle_error(joint))
            excess = max(0.0, error - self.deadband)
            scale = min(1.0, excess / max(1e-9, 1.0 - self.deadband))
            out[joint] = self.rest_hz + (self.full_hz - self.rest_hz) * scale
        self.rates = out
        return dict(out)

    def class_rates(self):
        """Mean rate of the joints a class measures, for a receipt."""
        out = {}
        for sensory in self.classes:
            values = [self.rates.get(joint, self.rest_hz) for joint in self.joints
                      if joint_class(joint) == sensory]
            if values:
                out[sensory] = sum(values) / len(values)
        return {name: round(value, 3) for name, value in out.items()}

    def events(self, tick_ms, dt_s=0.001, phase=None):
        """Map of neuron id -> spikes this tick; a joint fires its whole sheet together.

        ``phase`` is accepted for callers written against the per-cell version and is
        ignored: the phase now belongs to the joint, because a sheet that fires out of
        step is not the sensor the animal has and was measured not to propagate.
        """
        rates = self.rates_now()
        out = {}
        for joint in self.joints:
            cells = self.by_joint.get(joint)
            if not cells:
                continue
            value = self.phase[joint] + rates[joint] * dt_s
            if value >= 1.0:
                value -= 1.0
                self.sheets += 1
                for cell in cells:
                    out[cell] = 1
                    self.spikes += 1
                    self.fired[cell] = self.fired.get(cell, 0) + 1
            self.phase[joint] = value
        return out

    def record(self):
        sizes = [len(v) for v in self.by_joint.values()]
        assignment = ("proxy: class dealt over the joints of that class, "
                      "not a measured innervation")
        return {
            "classes": {name: len(ids) for name, ids in self.classes.items()},
            "joints": len(self.joints),
            "cells_per_joint": (min(sizes, default=0), max(sizes, default=0)),
            "rates_hz": self.class_rates(),
            "spikes": int(self.spikes),
            "sheets": int(self.sheets),
            "driven_cells": len({c for ids in self.by_joint.values() for c in ids}),
            "encoding": "a joint fires its sheet of sensilla on one millisecond",
            "assignment": assignment,
        }
