"""Tests for the twin body: muscles, mapping, posture and the walking loop."""

from __future__ import annotations

import math

import pytest

from service.infrastructure.body.motors import (
    LEG_REGIONS, LEG_TYPES, NEUROMERE_SEGMENTS, build_map, muscle_of_leg_neuron,
    muscles_of_abdominal_neuron, recruitment)
from service.infrastructure.body.muscles import Muscle, MuscleSet


def test_a_leg_motor_type_maps_to_one_named_muscle():
    assert muscle_of_leg_neuron("front_left", "Ti flexor MN") == "tibia_T1_left_flexor"
    assert muscle_of_leg_neuron("hind_right", "Ti extensor MN") == "tibia_T3_right_extensor"
    assert muscle_of_leg_neuron("front_left", "ltm MN") is None
    assert muscle_of_leg_neuron("unknown_region", "Ti flexor MN") is None


def test_an_abdominal_motor_drives_the_pitch_muscle_of_its_segment():
    pairs = muscles_of_abdominal_neuron("A3", "L")
    names = [name for name, _ in pairs]
    assert "abdomen_pitch_abdomen_3_flexor" in names
    assert "abdomen_yaw_abdomen_3_flexor" in names
    assert muscles_of_abdominal_neuron("A3", "R")[1][0] == "abdomen_yaw_abdomen_3_extensor"
    assert muscles_of_abdominal_neuron("A99", "L") == []


def test_sideways_direction_is_a_choice_not_a_measurement():
    left = dict(muscles_of_abdominal_neuron("A4", "L"))
    right = dict(muscles_of_abdominal_neuron("A4", "R"))
    assert set(left) != set(right)
    assert all(abs(value - 0.5) < 1e-12 for value in left.values())


def test_recruitment_is_a_rate_code_that_saturates():
    assert recruitment({1: 2}, [1]) == pytest.approx(0.1)
    assert recruitment({1: 30}, [1]) == pytest.approx(1.0)
    assert recruitment({1: 2}, [2]) == 0.0


def test_the_muscle_force_length_factor_peaks_at_rest_length():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05)
    peak = muscle.relative_force(0.05, 0.0)
    assert peak == pytest.approx(1.0)
    assert muscle.relative_force(0.05 * 1.4, 0.0) < peak
    assert muscle.relative_force(0.05 * 0.6, 0.0) < peak


def test_a_muscle_that_shortens_produces_less_force_than_one_held_still():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05)
    held = muscle.relative_force(0.05, 0.0)
    shortening = muscle.relative_force(0.05, -4.0)
    lengthening = muscle.relative_force(0.05, 4.0)
    assert shortening < held < lengthening


def test_activation_lags_a_step_command_and_never_passes_it():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05,
                    time_constant_s=0.005)
    muscle.advance(1.0, 0.001)
    first = muscle.activation
    assert 0.0 < first < 1.0
    for _ in range(200):
        muscle.advance(1.0, 0.001)
    assert muscle.activation > 0.9
    assert muscle.activation <= 1.0
    muscle.advance(0.0, 0.001)
    assert muscle.activation < 1.0



def test_the_series_element_leads_activation_inside_one_control_period():
    """A twitch must be able to start inside a 1 ms period, or the loop cannot steer."""
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05)
    muscle.advance(1.0, 0.001)
    assert muscle.activation < 0.3
    assert muscle.series > 0.6
    assert muscle.series > muscle.activation


def test_the_series_element_settles_onto_activation_not_beside_it():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05)
    for _ in range(200):
        muscle.advance(1.0, 0.001)
    assert abs(muscle.series - muscle.activation) < 1e-3
    for _ in range(200):
        muscle.advance(0.0, 0.001)
    assert abs(muscle.series - muscle.activation) < 1e-3


def test_the_moment_arm_is_one_at_the_perpendicular_pose_and_falls_from_it():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05,
                    travel_rad=0.2)
    assert muscle.arm_scale(0.0) == pytest.approx(1.0)
    near = muscle.arm_scale(0.05)
    far = muscle.arm_scale(0.2)
    assert 1.0 > near > far
    assert far >= 0.35 - 1e-12
    # Never above one: an unmeasured lever may not be invented upwards.
    for angle in (-0.2, -0.05, 0.0, 0.05, 0.2):
        assert muscle.arm_scale(angle) <= 1.0 + 1e-12


def test_a_shorter_moment_arm_makes_less_torque_at_the_same_activation():
    muscle = Muscle(name="m", joint="j", sign=1, leg=None, role="flexor",
                    peak_force_dyne=1.0, arm_cm=0.01, rest_length_cm=0.05,
                    travel_rad=0.2)
    muscle.advance(1.0, 0.0)
    straight = muscle.torque(0.05, 0.0, arm_scale=1.0)
    bent = muscle.torque(0.05, 0.0, arm_scale=0.5)
    assert bent == pytest.approx(0.5 * straight)


def test_the_muscle_set_reads_the_moment_arm_profile_from_the_descriptor():
    from pathlib import Path
    from service.infrastructure.body.muscles import MuscleSet
    path = Path(__file__).resolve().parents[1] / "service/infrastructure/body/assets/flybody-muscles.json"
    muscles = MuscleSet.load(path)
    travelled = [m for m in muscles.muscles.values() if m.travel_rad > 0.]
    assert len(travelled) > 100
    assert all(m.arm_scale(0.0) == 1.0 for m in travelled)
