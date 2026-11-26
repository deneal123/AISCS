"""Tests for the spike bridge and the behaviour loop that carries it."""

from __future__ import annotations

import pytest

from service.infrastructure.body.bridge import SpikeDrive, SPIKE_GAIN, TWITCH_DECAY_S


class _Set:
    """The muscle-set shape the bridge and the posture loop read."""

    def __init__(self, rows):
        self.muscles = dict(rows)
        self.order = list(rows)

    def by_joint(self, joint):
        return [self.muscles[name] for name in self.order if self.muscles[name].joint == joint]


class _Body:
    """The smallest body the bridge needs: a muscle set and the mapping."""

    def __init__(self, rows=None, mapping=None):
        rows = rows or {"tibia_T1_left_flexor": ("tibia_T1_left", -1),
                        "tibia_T1_left_extensor": ("tibia_T1_left", 1)}
        self.muscles = _Set({name: _Muscle(name, joint, sign)
                             for name, (joint, sign) in rows.items()})
        self.mapping = mapping or {"tibia_T1_left_flexor": [11, 12],
                                   "tibia_T1_left_extensor": [21]}

    def command_from_spikes(self, spikes, *, gain=0.05):
        out = {}
        for name, neurons in self.mapping.items():
            total = sum(spikes.get(neuron, 0) for neuron in neurons)
            out[name] = min(1.0, gain * total)
        return out


class _Muscle:
    def __init__(self, name, joint, sign):
        self.name = name
        self.joint = joint
        self.sign = sign
        self.peak_force_dyne = 1.0
        self.arm_cm = 0.01
        self.rest_length_cm = 0.05


def test_one_spike_outlives_the_tick_it_arrived_on():
    drive = SpikeDrive(_Body())
    drive.advance(0.001, {11: 1})
    first = drive.commands()["tibia_T1_left_flexor"]
    assert first == pytest.approx(SPIKE_GAIN)
    for _ in range(5):
        drive.advance(0.001)
    assert drive.commands()["tibia_T1_left_flexor"] > 0.0


def test_the_command_decays_with_the_twitch_constant():
    drive = SpikeDrive(_Body())
    drive.advance(0.001, {11: 1})
    start = drive.commands()["tibia_T1_left_flexor"]
    steps = int(round(TWITCH_DECAY_S / 0.001))
    for _ in range(steps):
        drive.advance(0.001)
    assert drive.commands()["tibia_T1_left_flexor"] < start * 0.5


def test_a_muscle_nobody_innervates_stays_silent():
    drive = SpikeDrive(_Body(mapping={"tibia_T1_left_flexor": [11],
                                     "tibia_T1_left_extensor": []}))
    drive.advance(0.001, {11: 5})
    assert drive.commands()["tibia_T1_left_extensor"] == 0.0
    assert drive.commands()["tibia_T1_left_flexor"] > 0.0


def test_repeated_spikes_sum_but_never_saturate_past_one():
    drive = SpikeDrive(_Body())
    for _ in range(50):
        drive.advance(0.001, {11: 3, 12: 3})
    assert drive.commands()["tibia_T1_left_flexor"] == pytest.approx(1.0)


def test_reset_clears_every_command():
    drive = SpikeDrive(_Body())
    drive.advance(0.001, {21: 2})
    drive.reset()
    assert all(value == 0.0 for value in drive.commands().values())
    assert drive.spikes_seen == 0


def test_a_spike_on_a_mapped_neuron_decides_that_the_fly_escapes():
    """Against the real body: the loop turns a burst into a decision and a latency."""
    try:
        from service.infrastructure.body.twin import TwinBody
        import mujoco  # noqa: F401
    except ImportError:  # pragma: no cover - the twin needs the physics engine
        pytest.skip("mujoco is not installed")
    from service.infrastructure.body.loop import BehaviourLoop
    body = TwinBody()
    loop = BehaviourLoop(body, compliance=1.0)
    loop.settle(steps=50)
    mapped = next(iter(loop._mapped))
    loop.advance(0.001, {int(mapped): 1})
    assert loop.escape_latency_ms is not None
    assert loop.escape.active


def test_a_spike_outside_the_motor_map_does_not_start_the_escape():
    try:
        from service.infrastructure.body.twin import TwinBody
        import mujoco  # noqa: F401
    except ImportError:  # pragma: no cover - the twin needs the physics engine
        pytest.skip("mujoco is not installed")
    from service.infrastructure.body.loop import BehaviourLoop
    from service.infrastructure.body.twin import TwinBody
    body = TwinBody()
    loop = BehaviourLoop(body, compliance=1.0)
    loop.settle(steps=50)
    unmapped = max(loop._mapped) + 1000
    loop.advance(0.001, {int(unmapped): 5})
    assert loop.escape_latency_ms is None

def test_only_spikes_that_reach_a_muscle_are_counted_as_motor_spikes():
    """The receipt used to add every spike, so a sensory burst looked like a motor one."""
    try:
        from service.infrastructure.body.twin import TwinBody
        import mujoco  # noqa: F401
    except ImportError:  # pragma: no cover - the twin needs the physics engine
        pytest.skip("mujoco is not installed")
    from service.infrastructure.body.loop import BehaviourLoop
    body = TwinBody()
    loop = BehaviourLoop(body, compliance=1.0)
    loop.settle(steps=50)
    unmapped = max(loop._mapped) + 1000
    # 400 spikes that no muscle listens to: the connectome would report 400 motor
    # spikes and zero recruitment, which is the defect this test pins.
    loop.advance(0.001, {int(unmapped): 400})
    assert loop.motor_spikes == 0
    mapped = next(iter(loop._mapped))
    loop.advance(0.001, {int(mapped): 3})
    assert loop.motor_spikes == 3
    assert loop.mapped_first_tick_ms is not None
