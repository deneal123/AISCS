"""Hill-type muscle model for the FlyBody twin.

Everything here is in the units of the source model: centimetre, gram, second,
so force is the dyne (1e-5 N) and torque is dyne*cm.  The whole fly weighs
0.966 dyne, which is what a real Drosophila weighs, so the numbers are directly
comparable to measured muscle forces instead of being an arbitrary scale.

A muscle has three factors:

  * recruitment u in [0, 1], the command the motor neuron carries;
  * activation a, a first-order lag on u with a 5 ms time constant;
  * a force-length factor and a force-velocity factor, both of which peak at 1.

force = peak_force_dyne * a * force_length(length) * force_velocity(velocity)

The force-length factor is a Gaussian around the optimal length, the
force-velocity factor is Hill's hyperbola for shortening and a linear cap for
lengthening.  Both are the standard forms and both are cheap enough to evaluate
inside the 0.1 ms physics step.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

FLAT_WIDTH = 0.55  # standard deviation of the force-length Gaussian, in l/l0
FV_SHORTENING_K = 0.25  # curvature of Hill's hyperbola
FV_LENGTHENING_CAP = 1.4  # a stretched muscle resists more than it pulls
VMAX_LENGTHS_PER_S = 8.0  # unloaded shortening speed, lengths per second


def force_length(normalized_length):
    """Gaussian force-length factor, 1 at the optimal length."""
    if not math.isfinite(normalized_length) or normalized_length <= 0.:
        return 0.
    offset = (normalized_length - 1.) / FLAT_WIDTH
    return math.exp(-0.5 * offset * offset)


def force_velocity(normalized_speed):
    """Hill force-velocity factor; positive speed means shortening.

    Shortening past the unloaded speed gives zero force, lengthening is damped
    but never reaches zero, which is what keeps a stretched muscle from
    behaving like a slack rope.  The argument is a shortening speed, while the
    physics reports a length rate, so relative_force flips the sign: a muscle
    whose length is falling is shortening.
    """
    if not math.isfinite(normalized_speed):
        return 0.
    if normalized_speed >= 1.:
        return 0.
    if normalized_speed >= 0.:
        return (1. - normalized_speed) / (1. + normalized_speed / FV_SHORTENING_K)
    return min(FV_LENGTHENING_CAP, 1. - normalized_speed * 0.5)


@dataclass
class Muscle:
    """One muscle: identity, geometry and the state carried between steps."""

    name: str
    joint: str
    sign: int
    leg: str
    role: str
    peak_force_dyne: float
    arm_cm: float
    rest_length_cm: float
    time_constant_s: float = 0.005
    activation: float = 0.0

    def torque(self, length_cm, speed_cm_s, activation=None):
        """Joint torque in dyne*cm, signed so that a positive command is flexion."""
        a = self.activation if activation is None else activation
        if a <= 0. or self.arm_cm <= 0. or self.rest_length_cm <= 0.:
            return 0.
        force = self.peak_force_dyne * a * self.relative_force(length_cm, speed_cm_s)
        return force * self.arm_cm * self.sign

    def relative_force(self, length_cm, speed_cm_s):
        """Force-length and force-velocity factors together, both near 1 at rest."""
        if self.rest_length_cm <= 0.:
            return 0.
        normalized = length_cm / self.rest_length_cm
        # The caller supplies d(length)/dt, so a negative rate is a shortening
        # muscle; force_velocity wants the shortening speed.
        shortening = -speed_cm_s / (self.rest_length_cm * VMAX_LENGTHS_PER_S)
        return force_length(normalized) * force_velocity(shortening)

    def advance(self, command, dt_s):
        """First-order activation towards the command, exact for a constant input."""
        command = 0. if not math.isfinite(command) else min(1., max(0., command))
        if dt_s <= 0.:
            self.activation = command
            return self.activation
        decay = math.exp(-dt_s / self.time_constant_s)
        self.activation = command + (self.activation - command) * decay
        return self.activation


@dataclass
class MuscleSet:
    """The full set of muscles of one animal, indexed by joint."""

    muscles: dict
    order: list = field(default_factory=list)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("format") != "aspa.flybody.muscles" or payload.get("version") != 1:
            raise ValueError("Unsupported muscle descriptor")
        muscles = {}
        order = []
        for row in payload["muscles"]:
            muscle = Muscle(
                name=row["name"],
                joint=row["joint"],
                sign=int(row["sign"]),
                leg=row.get("leg") or row.get("part") or "",
                role=row["role"],
                peak_force_dyne=float(row["peak_force_dyne"]),
                arm_cm=float(row["arm_cm"]),
                rest_length_cm=float(row.get("rest_length") or row.get("segment_length") or 0.),
                time_constant_s=float(payload.get("time_constant_s", 0.005)),
            )
            muscles[muscle.name] = muscle
            order.append(muscle.name)
        return cls(muscles=muscles, order=order)

    def by_joint(self, joint):
        return [self.muscles[name] for name in self.order if self.muscles[name].joint == joint]

    def advance(self, commands, dt_s):
        """Advance every muscle; ``commands`` maps muscle name to recruitment."""
        for name in self.order:
            self.muscles[name].advance(commands.get(name, 0.), dt_s)

    def torques(self, lengths, speeds):
        """Torque per joint, dyne*cm, summing the muscles that cross it."""
        totals = {}
        for name in self.order:
            muscle = self.muscles[name]
            totals[muscle.joint] = totals.get(muscle.joint, 0.) + muscle.torque(
                lengths.get(muscle.joint, muscle.rest_length_cm),
                speeds.get(muscle.joint, 0.))
        return totals

    def activations(self):
        return {name: self.muscles[name].activation for name in self.order}

