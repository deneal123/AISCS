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

