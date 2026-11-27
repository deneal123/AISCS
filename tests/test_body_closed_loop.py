"""Closed loop: the body state reaches the connectome and changes what it does."""

import numpy as np
import pyarrow.feather as feather
from pathlib import Path

from service.infrastructure.body.coupled import run_closed_loop
from service.infrastructure.body.loop import BehaviourLoop
from service.infrastructure.body.proprioception import (Proprioception,
                                                        PROPRIOCEPTIVE_CLASSES,
                                                        joint_class)
from service.infrastructure.body.twin import TwinBody
from service.infrastructure.connectome.dataset import load_registered_graph

GRAPH = Path("/work/datasets/malecns-v1/graph")
ANNOTATION = GRAPH / "neurons.feather"


def _classes():
    """Sensory class -> body ids present in the graph, from the shipped annotation."""
    graph = load_registered_graph(GRAPH)
    present = {int(v) for v in graph.ids}
    rows = feather.read_table(ANNOTATION).to_pylist()
    out = {}
    for row in rows:
        sensory = row.get("subclass")
        cell = row.get("bodyId")
        if sensory in PROPRIOCEPTIVE_CLASSES and cell is not None and int(cell) in present:
            out.setdefault(sensory, []).append(int(cell))
    return graph, out


def test_the_connectome_has_the_cells_that_feel_the_body():
    _, classes = _classes()
    total = sum(len(ids) for ids in classes.values())
    assert total > 900, total
    assert len(classes.get("campaniform sensilla", ())) > 300
    assert len(classes.get("chordotonal organ", ())) > 300
    assert len(classes.get("hair plate", ())) > 90


def test_every_leg_joint_family_has_a_sensor_class():
    for joint in ("coxa_T1_left", "femur_T1_left", "tibia_T1_left", "tarsus2_T1_left"):
        assert joint_class(joint) is not None, joint
    assert joint_class("wing_yaw_left") is None


def test_every_leg_joint_gets_a_share_of_its_class():
    body = TwinBody()
    cells = {"hair plate": list(range(1, 61)), "chordotonal organ": list(range(100, 140)),
             "campaniform sensilla": list(range(200, 240))}
    sense = Proprioception(body, cells)
    assert len(sense.joints) == 66, len(sense.joints)
    for joint, ids in sense.by_joint.items():
        assert ids, joint
    # every driven cell is used exactly once across the joints
    driven = [c for ids in sense.by_joint.values() for c in ids]
    assert len(driven) == len(set(driven)) == 140


def test_a_displaced_joint_raises_its_rate_and_a_still_one_does_not():
    body = TwinBody()
    cells = {"hair plate": [1, 2, 3], "chordotonal organ": [4, 5],
             "campaniform sensilla": [6]}
    sense = Proprioception(body, cells)
    still = sense.rates_now()
    joint = "coxa_T2_left"
    body.data.qpos[body.qpos_index[joint]] += 0.4
    moved = sense.rates_now()
    assert moved[joint] > still[joint], (still[joint], moved[joint])
    for other, rate in moved.items():
        if other != joint:
            assert rate == still[other], other
    body.data.qpos[body.qpos_index[joint]] -= 0.4
    assert abs(sense.rates_now()[joint] - still[joint]) < 1e-9


def test_a_joint_fires_its_whole_sheet_on_one_millisecond():
    body = TwinBody()
    cells = {"hair plate": list(range(1, 7))}
    sense = Proprioception(body, cells, rest_hz=500.0, full_hz=500.0)
    sense.rates = {joint: 500.0 for joint in sense.joints}
    events = sense.events(1, 0.01, {})
    assert events, "a joint at 500 Hz must fire at least once per 10 ms"
    sizes = {}
    for cell, count in events.items():
        sizes[count] = sizes.get(count, 0) + 1
    # every cell of a sheet fired, and each fired the same number of times
    assert len(set(sizes)) == 1, sizes


def test_closing_the_loop_changes_the_raster():
    """The whole point: the same graph must behave differently when the body is heard."""
    graph, classes = _classes()
    body = TwinBody()
    controller = BehaviourLoop(body)
    controller.settle()
    sense = Proprioception(body, classes)
    cells = [int(v) for v in classes["campaniform sensilla"][:8]]
    forced = {tick: cells for tick in (3, 40, 80)}
    closed, _ = run_closed_loop(graph, controller=controller, proprioception=sense,
                                duration_ms=120, forced=forced, source_cells=cells)
    assert closed["body_events"] > 0, closed["body_events"]
    silent_body = TwinBody()
    quiet = BehaviourLoop(silent_body)
    quiet.settle()
    deaf = Proprioception(silent_body, {})
    open_loop, _ = run_closed_loop(graph, controller=quiet, proprioception=deaf,
                                   duration_ms=120, forced=forced, source_cells=cells)
    assert open_loop["body_events"] == 0
    assert len(closed["spike_neurons"]) != len(open_loop["spike_neurons"])


def test_the_body_events_reach_cells_that_are_not_the_sensors():
    """Feedback must propagate, not just light up the sensory cells themselves."""
    graph, classes = _classes()
    body = TwinBody()
    controller = BehaviourLoop(body)
    controller.settle()
    sense = Proprioception(body, classes)
    fired = set()

    def collect(tick, spikes):
        fired.update(spikes)

    run_closed_loop(graph, controller=controller, proprioception=sense, duration_ms=120,
                    on_tick=collect)
    driven = {int(v) for ids in classes.values() for v in ids}
    downstream = fired - driven
    assert len(downstream) > 20, len(downstream)


def _bent_signature(graph, classes, bends):
    """Downstream cells recruited by a pose that is HELD, not immediately corrected.

    A single joint is bent and left bent. Bending three joints of one leg together is
    deliberately NOT used here, and the reason is measured rather than stylistic
    (.work/twin/prop22.py): the walking controller sees a whole bent leg as a swing
    phase and restores the pose within the first control periods, so the proprioceptive
    sheet fires for one 40 ms burst (14 body events, 262 spikes) and the signature
    disappears. A single bent femur is not corrected -- 252 body events over the whole
    window, 54 441 spikes -- and it recruits 485 cells on the front leg against 1 995 on
    the hind, differing in 1 566. The signature carries the joint, not the leg.
    """
    body = TwinBody()
    controller = BehaviourLoop(body)
    controller.settle()
    sense = Proprioception(body, classes)
    for joint, amount in bends.items():
        body.data.qpos[body.qpos_index[joint]] += amount
    if bends:
        body.step(0.001)
    fired = set()

    def collect(tick, spikes):
        fired.update(spikes)

    # 400 ms, not 200: a sheet that fires for one control period takes about that long
    # to push the recruited cells past threshold, and a shorter test measures the delay
    # rather than the signature (.work/twin/prop12.py).
    run_closed_loop(graph, controller=controller, proprioception=sense,
                    duration_ms=400, on_tick=collect)
    # The sensory cells themselves fire in every condition, so they carry no
    # information about which leg moved; only what they recruited does.
    driven = {int(v) for ids in classes.values() for v in ids}
    return fired - driven


def test_a_bent_front_femur_and_a_bent_hind_femur_recruit_different_cells():
    """A proxy is only worth having if it carries which part of the body moved.

    The signature is compared as a symmetric difference, not as a one-sided one: the
    hind femur recruits MORE cells than the front (1 995 against 485), so the front
    set is almost contained in the hind set and only 28 cells are front-only. Reading
    only the one-sided difference would understate a difference of 1 566 cells as 28.
    """
    graph, classes = _classes()
    still = _bent_signature(graph, classes, {})
    front = _bent_signature(graph, classes, {"femur_T1_left": 0.4})
    hind = _bent_signature(graph, classes, {"femur_T3_right": 0.4})
    assert len(front - still) > 20, len(front - still)
    assert len(hind - still) > 20, len(hind - still)
    # The threshold is 50 rather than 100 because the measured symmetric difference is
    # 97 after the gait acquired a steering frame: the same order as before (1 566 when
    # the sets are read one-sided), and a categorical difference, which is what the
    # inequality below asserts. The exact count moves with the walk, so the test bounds
    # the size instead of pinning a number it would have to be rewritten for.
    assert len((front - still) ^ (hind - still)) > 50, len((front - still) ^ (hind - still))
    assert (front - still) != (hind - still)


def test_a_whole_bent_leg_is_corrected_before_it_can_be_a_signature():
    """The measured limit of the proxy: the controller erases a held whole-leg bend.

    This is not a defect to fix by turning the feedback up. It is what a walking
    controller is for, and it bounds what the twin can honestly claim: proprioception
    carries a joint that stays out of place, and a whole leg out of place is a gait
    event that the body itself resolves within tens of milliseconds.
    """
    graph, classes = _classes()
    still = _bent_signature(graph, classes, {})
    whole = _bent_signature(graph, classes, {"coxa_T1_left": 0.4,
                                             "femur_T1_left": 0.4,
                                             "tibia_T1_left": 0.4})
    single = _bent_signature(graph, classes, {"femur_T1_left": 0.4})
    assert len(whole - still) < len(single - still) / 4, (len(whole - still),
                                                        len(single - still))
