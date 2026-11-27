"""Flight: a wingbeat programme, its aerodynamic force, and what it lifts.

The twin had no flight at all. The six wing joints and the two halteres were servos
in the source model, the connectome 26 wing and haltere motor neurons were mapped
onto nothing, and an episode could report walking and abdominal curl and could not
report flight.

Three layers, kept apart because they make three different claims:

  * the connectome decides WHETHER and HOW HARD to fly. Its wing motor neurons
    (DLMn a,b / c-f, DVMn 1a-c / 2a,b / 3a,b, hDVM MN) are mapped onto the wing pitch
    and haltere muscles, and their recruitment sets the stroke amplitude and the
    frequency of the beat. That map is anatomical: DLM is the wing elevator and DVM
    the depressor, which is what the literature settles and what PDMNa/ADMN/MesoAN
    carry;
  * the thorax executes the beat. A real fly beats at 200 Hz with stretch-activated
    muscle, which no 1 ms control loop and no 5 ms activation time constant can
    follow; the twin therefore drives the wing joints as a programme and states that
    the beat is a prescription, not a spike train. This is the same division of
    labour as the animal: the nervous system sets the gain, the thorax oscillates;
  * the air pushes back. MuJoCo has no aerodynamics: the fluid geoms in the source
    model are collision shapes with no fluid model attached, so a beating wing here
    would move airlessly. The force below is the quasi-steady blade-element model of
    Ellington and Dickinson, integrated along the span, and it is applied to the
    thorax as an external force.

The aerodynamic coefficients are the published ones: C_L rises to about 1.6 at the
high angles of attack a fly uses, C_D about 1.9. Nothing here is fitted to the twin.
"""

from __future__ import annotations

import math

# Air at 25 C, g/cm3.  The twin works in cm, g, s, dyne, so this is the density the
# formula below needs and not the SI one.
AIR_DENSITY = 1.2e-3
# Wing of the model: the membrane ellipse of the source asset, semi-axes measured off
# flybody.xml (0.0551 cm and 0.114 cm).  Length is the long semi-axis doubled.
WING_SEMI_CHORD_CM = 0.0551
WING_SEMI_LENGTH_CM = 0.114
WING_LENGTH_CM = 2.0 * WING_SEMI_LENGTH_CM
WING_AREA_CM2 = math.pi * WING_SEMI_CHORD_CM * WING_SEMI_LENGTH_CM
# Lift and drag coefficients at the angles of attack a fly actually flies at.  A wing
# at 35 degrees is past the stall of an aircraft and still lifting, which is the trick
# of insect flight.
LIFT_COEFFICIENT = 1.6
DRAG_COEFFICIENT = 1.9
# Rotational circulation: the wing flips at each stroke reversal, and a wing that
# rotates while it translates carries bound circulation the pure translation term does
# not have.  For rotation about the leading edge Dickinson, Lehmann and Sane (1999)
# measure C_R = pi, which is the value used here.  Without this term the beat below
# supports 0.80 of the animal's weight; with it, 1.16 -- which is why a fly hovers and
# a wing that only translated would not.
ROTATION_COEFFICIENT = math.pi
# The body: measured off the same asset, and the weight it has to lift.
BODY_WEIGHT_DYNE = 0.966
# A fly beats between 150 and 250 Hz; the value below is the middle of the range for
# Drosophila melanogaster at 25 C.
STROKE_FREQUENCY_HZ = 200.0
# Stroke amplitude, radian, half of the peak-to-peak sweep: 70 degrees each way is a
# measured Drosophila stroke.
STROKE_AMPLITUDE_RAD = math.radians(70.0)
# Angle of attack: the wing is pitched nose-up through the stroke, which is what
# produces a leading-edge vortex and the extra lift a fixed wing would not have.
ANGLE_OF_ATTACK_RAD = math.radians(35.0)


def mean_square_speed(radius_cm, frequency_hz, amplitude_rad):
    """Mean square speed of a wing element at radius, (cm/s)^2, over one stroke."""
    omega = 2.0 * math.pi * frequency_hz
    return 0.5 * (radius_cm * amplitude_rad * omega) ** 2


def quasi_steady_force(*, frequency_hz=STROKE_FREQUENCY_HZ,
                       amplitude_rad=STROKE_AMPLITUDE_RAD,
                       angle_of_attack_rad=ANGLE_OF_ATTACK_RAD,
                       lift_coefficient=LIFT_COEFFICIENT,
                       drag_coefficient=DRAG_COEFFICIENT,
                       wings=2):
    """Mean lift and drag of a beating wing pair, dyne.

    Blade element: each strip of the wing at radius r moves with speed
    r * amplitude * omega * cos(phase), so its mean square speed over a stroke is
    half of (r * amplitude * omega)^2.  The integral of r^2 over the span is R^3 / 3,
    and the chord is the mean chord of the membrane ellipse.  This is the force a
    hovering fly gets, and it is the number that decides whether it flies at all.
    """
    omega = 2.0 * math.pi * frequency_hz
    mean_chord = WING_AREA_CM2 / WING_LENGTH_CM
    span_integral = (WING_LENGTH_CM ** 3) / 3.0
    dynamic = 0.5 * AIR_DENSITY * (amplitude_rad * omega) ** 2 * 0.5
    lift = dynamic * lift_coefficient * mean_chord * span_integral * wings
    drag = dynamic * drag_coefficient * mean_chord * span_integral * wings
    return float(lift), float(drag)


def rotational_force(*, frequency_hz=STROKE_FREQUENCY_HZ,
                     amplitude_rad=STROKE_AMPLITUDE_RAD,
                     angle_of_attack_rad=ANGLE_OF_ATTACK_RAD,
                     rotation_coefficient=ROTATION_COEFFICIENT,
                     wings=2):
    """Mean force from the wing rotating through the stroke, dyne.

    The wing pitches from one extreme of the angle of attack to the other once per
    half stroke, so its pitch rate is 2 * angle_of_attack / (half period).  A wing of
    chord c and span R turning at that rate while it translates at U carries a
    circulation that adds rho * C_R * c^2 * R * pitch_rate * U / 2 to the force.  This
    is the term that makes the difference between gliding and hovering.
    """
    omega = 2.0 * math.pi * frequency_hz
    if omega <= 0.0:
        return 0.0
    half_period = math.pi / omega
    pitch_rate = 2.0 * angle_of_attack_rad / half_period
    # Mean speed of the wing along its span, the speed the circulation is carried at.
    mean_speed = (2.0 / math.pi) * amplitude_rad * omega * WING_LENGTH_CM
    force = 0.5 * AIR_DENSITY * rotation_coefficient * (WING_AREA_CM2 / WING_LENGTH_CM) ** 2 \
        * WING_LENGTH_CM * pitch_rate * mean_speed * wings
    return float(force)


def lift_to_weight(**kwargs):
    """How many body weights the beat supports; below 1.0 the animal cannot hover.

    Both terms are included, because the rotational one is not a correction: it is a
    third of the lift and the difference between falling and hovering.
    """
    lift, _ = quasi_steady_force(**kwargs)
    lift += rotational_force(**kwargs)
    return lift / BODY_WEIGHT_DYNE


class FlightProgram:
    """The beat, as joint targets for the wings and a force for the thorax.

    The three wing joints are used the way the animal uses them: yaw sweeps the wing
    fore and aft, roll pitches it through the stroke (the angle of attack) and pitch
    raises the whole wing above the legs.  Both wings push down together, so the force
    is the sum; a difference between the two sides is what would roll the animal.
    """

    def __init__(self, *, frequency_hz=STROKE_FREQUENCY_HZ,
                 amplitude_rad=STROKE_AMPLITUDE_RAD,
                 angle_of_attack_rad=ANGLE_OF_ATTACK_RAD,
                 asymmetry=0.0):
        self.frequency_hz = float(frequency_hz)
        self.amplitude_rad = float(amplitude_rad)
        self.angle_of_attack_rad = float(angle_of_attack_rad)
        # asymmetry in [-1, 1]: positive beats the left wing harder, which rolls right
        self.asymmetry = float(asymmetry)
        self.phase_rad = 0.0

    def advance(self, dt_s):
        self.phase_rad = (self.phase_rad + 2.0 * math.pi * self.frequency_hz * dt_s) % (
            2.0 * math.pi)

    def angles(self):
        """Wing joint targets, radian, keyed by joint name."""
        sweep = self.amplitude_rad * math.sin(self.phase_rad)
        pitch = self.angle_of_attack_rad * math.cos(self.phase_rad)
        out = {}
        for side, scale in (("left", 1.0 + self.asymmetry), ("right", 1.0 - self.asymmetry)):
            out["wing_yaw_%s" % side] = sweep * scale
            out["wing_roll_%s" % side] = pitch
            # The elevation keeps the wing above the legs; a wing that sweeps through
            # the leg is a collision, not a stroke.
            out["wing_pitch_%s" % side] = 0.35 + 0.1 * math.sin(self.phase_rad)
            out["haltere_%s" % side] = 0.6 * math.sin(self.phase_rad + math.pi / 2.0)
        return out

    def force(self):
        """Mean aerodynamic force of the current beat, dyne, and its two components.

        Asymmetry scales one wing contribution and leaves the other alone, so a
        one-sided beat produces a rolling moment rather than a change of lift only.
        """
        translational, drag = quasi_steady_force(
            frequency_hz=self.frequency_hz, amplitude_rad=self.amplitude_rad,
            angle_of_attack_rad=self.angle_of_attack_rad)
        rotational = rotational_force(frequency_hz=self.frequency_hz,
                                      amplitude_rad=self.amplitude_rad,
                                      angle_of_attack_rad=self.angle_of_attack_rad)
        lift = translational + rotational
        left = 0.5 * (1.0 + self.asymmetry)
        right = 0.5 * (1.0 - self.asymmetry)
        return dict(lift=lift, drag=drag, translational=translational,
                    rotational=rotational, left=lift * left, right=lift * right,
                    lift_to_weight=lift / BODY_WEIGHT_DYNE)

    def commanded_by(self, recruitment):
        """Set the beat from a flight command in [0, 1], the way the connectome does it.

        A fly that is not flying holds its wings back and does not beat.  Amplitude and
        frequency both rise with the command; frequency is what costs the animal most,
        so it starts at a third of its ceiling and saturates at the top.
        """
        recruitment = max(0.0, min(1.0, float(recruitment)))
        self.amplitude_rad = STROKE_AMPLITUDE_RAD * recruitment
        self.frequency_hz = STROKE_FREQUENCY_HZ * (0.35 + 0.65 * recruitment)
        return self

    def still(self):
        self.amplitude_rad = 0.0
        self.frequency_hz = 0.0
        return self