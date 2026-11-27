"""The behaviours the twin can actually perform, each one measured.

Walking and escaping were the only two programmes the body had.  Four more are
needed before a synthetic corpus can hold anything but a walk and a bolt, and each
one here was measured on the body before it was written down (the numbers are in
the docstrings, the runs are in .work/twin/repertoire3.py and
.work/twin/turnplace.py, .work/twin/lift.py):

  * "walk"          -- forward tripod gait, 9.5 mm in 600 ms, heading drift -2.3 deg;
  * "back"          -- the same gait with the stroke reversed and the phase still
                       running forward, 7.67 mm backwards in 600 ms, drift -1.2 deg.
                       Reversing the phase instead walks backwards too but yaws
                       16.5 deg, because the swing foot then leads with the wrong
                       leg pair;
  * "turn_in_place" -- steering with no stride, -61.4 deg in 600 ms while the body
                       moves 0.61 mm: a pivot, not a circle.  With the stride left on
                       it covers 16.15 mm, which is a circle;
  * "groom"         -- the animal stops and raises both front claws by 0.05 cm and
                       sweeps them.  The foot-space lift is what works: a joint-space
                       pose moved the claw by -0.005 cm at best, because the femur and
                       tibia rotate the tarsus about a point that is not the claw.
                       0.05 cm is the largest rise the stance still carries; 0.10 cm
                       tips the body 0.033 cm down;
  * "freeze"        -- no stride and no steering: the animal stands, 0.7 mm of drift
                       in 600 ms.

A behaviour is a prescription, exactly like the gait and for the same reason: it says
what the legs are told to do, not what the connectome decided.  Only the escape is
driven by the connectome, which is why the escape is where the measurements live.

Units are the twin units: centimetre, radian, second.
"""

from __future__ import annotations

import math

import numpy as np

from .kinematics import LEGS

# Names as they are written into an episode and a dataset row.
WALK = "walk"
BACK = "back"
TURN_IN_PLACE = "turn_in_place"
GROOM = "groom"
FREEZE = "freeze"

BEHAVIOURS = (WALK, BACK, TURN_IN_PLACE, GROOM, FREEZE)

# A front claw is raised this far for grooming, cm.  Measured: 0.05 cm is held and the
# other four claws stay on the floor; 0.10 cm tips the body down by 0.033 cm and the
# claw reaches only 0.05-0.09 cm of the 0.10 asked for.
GROOM_LIFT_CM = 0.05
# How far the front pair sweeps while grooming, rad.
GROOM_SWEEP_RAD = 0.28


class Behaviour:
    """A named programme for the gait: how fast to step, how long the stroke is, which way to steer."""

    __slots__ = ("name", "stride_rate", "stroke_scale", "turn", "front_lift_cm")

    def __init__(self, name, *, stride_rate=1.0, stroke_scale=1.0, turn=0.0,
                 front_lift_cm=0.0):
        if name not in BEHAVIOURS:
            raise ValueError("Unknown behaviour %r; known: %s"
                             % (name, ", ".join(BEHAVIOURS)))
        self.name = str(name)
        self.stride_rate = float(stride_rate)
        self.stroke_scale = float(stroke_scale)
        self.turn = float(turn)
        self.front_lift_cm = float(front_lift_cm)

    def __repr__(self):
        return ("Behaviour(%r, stride_rate=%g, stroke_scale=%g, turn=%g, front_lift_cm=%g)"
                % (self.name, self.stride_rate, self.stroke_scale, self.turn,
                   self.front_lift_cm))

    def moves(self):
        """Whether the animal is going anywhere."""
        return self.stride_rate != 0.0 and self.stroke_scale != 0.0


def walk():
    return Behaviour(WALK)


def back():
    # Stroke negative, phase forward: reversing the phase as well yaws the animal by
    # 16.5 degrees in 600 ms (measured), which is a turn the caller did not ask for.
    #
    # The rate is 0.65, not 1.0, because at the retuned 90 ms period a full-rate
    # reversal yaws the body 13.7 degrees in 600 ms: the same claws that hold a
    # forward stance at 19.5 mm/s cannot drag it backwards that fast without the
    # front pair losing grip.  Measured in .work/twin/bs1.log, rate 1.0 -> 13.74
    # degrees and the body rides 0.0315 cm up, 0.8 -> -1.02, 0.65 -> 1.75 with the
    # body at 0.0022 cm, 0.5 -> 1.35 but the body sinks to -0.0015 cm.  Slower than
    # a real fly backs up, and straight.
    return Behaviour(BACK, stride_rate=0.65, stroke_scale=-1.0)


def turn_in_place(*, direction=-1.0):
    # No stride at all: a stride here drags the body 16.15 mm while it pivots.
    return Behaviour(TURN_IN_PLACE, stride_rate=0.0, stroke_scale=0.0,
                     turn=float(direction))


def groom():
    return Behaviour(GROOM, stride_rate=0.0, stroke_scale=0.0, front_lift_cm=GROOM_LIFT_CM)


def freeze():
    return Behaviour(FREEZE, stride_rate=0.0, stroke_scale=0.0)


def named(name, *, direction=-1.0):
    """The behaviour with this name; a turn takes the side it should turn to."""
    if name == WALK:
        return walk()
    if name == BACK:
        return back()
    if name == TURN_IN_PLACE:
        return turn_in_place(direction=direction)
    if name == GROOM:
        return groom()
    if name == FREEZE:
        return freeze()
    raise ValueError("Unknown behaviour %r; known: %s" % (name, ", ".join(BEHAVIOURS)))


def front_lift_targets(gait, lift_cm, *, sweep=0.0, legs=("T1_left", "T1_right")):
    """Joint targets that raise the named claws by lift_cm and sweep them sideways.

    The lift is solved in foot space, not posed in joint space: a joint-space pose was
    measured to move the claw by -0.005 cm at best, because the femur and tibia rotate
    the tarsus chain about a point that is not the claw.  The sweep is a sideways
    offset of the same foot-space goal, so it cannot move the claw off the animal.
    """
    out = {}
    lift = float(lift_cm)
    for index, leg in enumerate(legs):
        here = gait.kinematics.foot(leg)
        sign = 1.0 if index % 2 == 0 else -1.0
        goal = np.array([here[0] + sign * float(sweep), here[1], here[2] + lift])
        angles, _error = gait.kinematics.solve(leg, goal, guess=gait.kinematics.angles(leg))
        for name, value in zip(gait.kinematics.joints[leg], angles):
            out[name] = float(value)
    return out


def claw_heights(gait):
    """Where each claw stands, cm; the measure a behaviour is checked against."""
    return {leg: float(gait.kinematics.foot(leg)[2]) for leg in LEGS}
