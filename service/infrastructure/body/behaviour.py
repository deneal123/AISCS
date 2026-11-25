"""Behaviour for the twin: standing, walking and escaping.

The twin has muscles and a body, but no nervous system of its own: the connectome
decides which neurons fire, and this module turns that into the joint targets a
walking insect uses.  Two behaviours are implemented, because they are the two the
pain dataset needs:

  * a tripod gait, the gait a fly actually uses, so the body can be somewhere else
    a moment after a stimulus;
  * an escape, the measured defensive response: the abdomen curls, the legs extend,
    and the animal moves away from where the noxious stimulus landed.

The gait is open loop.  That is a deliberate limit: this is a kinematic
prescription for the legs, not a claim that the connectome produced it.  What the
connectome does produce is the escape, which is why the escape is where the
measurements live.

Units are the twin units: centimetre, radian, second.
"""

from __future__ import annotations

import math

# Tripod gait: these three legs swing together, the other three support.
TRIPOD_A = ("T1_left", "T2_right", "T3_left")
TRIPOD_B = ("T1_right", "T2_left", "T3_right")
GAIT_PERIOD_S = 0.12  # a fly takes about eight steps a second
SWING_FRACTION = 0.4  # share of the cycle a leg is in the air
SWING_AMPLITUDE_RAD = 0.22  # fore-aft sweep of the coxa
LIFT_AMPLITUDE_RAD = 0.16  # knee lift during swing
TIBIA_FLEX_RAD = 0.20

# Escape: the measured response to a noxious stimulus.  The abdomen curls upward
# over about 300 ms, the legs extend, and the animal walks away faster than it
# walks when undisturbed.
ESCAPE_CURL_RAD = 0.10
ESCAPE_LEG_EXTENSION_RAD = 0.12
ESCAPE_GAIT_SCALE = 2.2
ESCAPE_DURATION_S = 0.35
ESCAPE_ONSET_S = 0.012  # measured: the first motor spike comes at 9-12 ms


class Gait:
    "Open-loop tripod gait, expressed as joint targets."

    def __init__(self, period_s=GAIT_PERIOD_S, amplitude=SWING_AMPLITUDE_RAD):
        self.period_s = float(period_s)
        self.amplitude = float(amplitude)
        self.phase = 0.0

    def advance(self, dt_s):
        self.phase = (self.phase + dt_s / self.period_s) % 1.0
        return self.phase

    def targets(self, offset=0.0):
        "Joint target for every leg joint at the current phase."
        out = {}
        for tripod, shift in ((TRIPOD_A, 0.0), (TRIPOD_B, 0.5)):
            local = (self.phase + shift) % 1.0
            swing = local < SWING_FRACTION
            if swing:
                progress = local / SWING_FRACTION
                sweep = -1.0 + 2.0 * progress
                lift = math.sin(math.pi * progress)
            else:
                progress = (local - SWING_FRACTION) / (1.0 - SWING_FRACTION)
                sweep = 1.0 - 2.0 * progress
                lift = 0.0
            for leg in tripod:
                # Kinematics, measured with the joint moved on its own: a
                # negative femur angle and a positive tibia angle both raise the
                # claw, and a positive coxa_abduct angle swings it backwards.
                out["coxa_abduct_%s" % leg] = offset + self.amplitude * sweep
                out["femur_%s" % leg] = -LIFT_AMPLITUDE_RAD * lift
                out["tibia_%s" % leg] = TIBIA_FLEX_RAD * lift
        return out


class Escape:
    "The defensive response, driven by whatever the connectome decided."

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
        "Response strength in [0, 1]: fast onset, slower relaxation."
        if self.elapsed is None or self.elapsed < 0:
            return 0.0
        progress = self.elapsed / self.duration_s
        rise = min(1.0, progress / 0.15)
        fall = 1.0 if progress < 0.5 else max(0.0, 1.0 - (progress - 0.5) / 0.5)
        return rise * fall

    def targets(self, segments):
        "Abdominal curl and leg extension for the current envelope."
        amount = self.envelope()
        if amount <= 0.0:
            return {}
        out = {}
        for segment in segments:
            out["abdomen_pitch_%s_flexor" % segment] = amount * ESCAPE_CURL_RAD
            # The yaw pair bends the abdomen away from the stimulus side.
            if self.side != 0.0:
                direction = "flexor" if self.side > 0 else "extensor"
                out["abdomen_yaw_%s_%s" % (segment, direction)] = amount * ESCAPE_CURL_RAD * 0.5
        for leg in TRIPOD_A + TRIPOD_B:
            out["tibia_%s" % leg] = -amount * ESCAPE_LEG_EXTENSION_RAD
        return out


def blend(gait_targets, escape_targets, *, escape_scale=1.0):
    "Combine the gait and the escape; the escape wins where they overlap."
    out = dict(gait_targets)
    for joint, value in escape_targets.items():
        out[joint] = out.get(joint, 0.0) + value * escape_scale
    return out
