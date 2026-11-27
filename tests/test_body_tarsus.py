"""The tarsal chain, the mouthparts and the antennae have to move when commanded.

The twin used to actuate only the first tarsal joint and left the four distal
segments passive, and it left the whole head passive as well.  A joint with no
muscle is not a simplification, it is a defect: the free tarsal segments bent under
load and ate the push the tibia delivered, and the head carried 14.5 percent of the
body weight through free hinges.  These tests pin the drive down so it cannot
quietly disappear again.
"""

import numpy as np
import pytest

try:
    import mujoco
except ImportError:  # the shim has no importorskip
    pytest.skip("mujoco is not installed", allow_module_level=True)

from service.infrastructure.body.loop import BehaviourLoop
from service.infrastructure.body.twin import TwinBody

TARSAL = [pattern.format(leg=leg) for leg in
          ("T1_left", "T1_right", "T2_left", "T2_right", "T3_left", "T3_right")
          for pattern in ("tarsus_{leg}", "tarsus2_{leg}", "tarsus3_{leg}",
                          "tarsus4_{leg}", "tarsus5_{leg}")]
MOUTH = ["head_abduct", "head_twist", "head", "rostrum", "haustellum_abduct",
         "haustellum", "labrum_left", "labrum_right",
         "antenna_abduct_left", "antenna_twist_left", "antenna_left",
         "antenna_abduct_right", "antenna_twist_right", "antenna_right"]


def _actuators(body, joint):
    """Every actuator whose transmission is this joint, as name -> signed peak torque."""
    out = {}
    for name in body.muscles.muscles:
        actuator = body.model.actuator(name)
        if int(actuator.trntype[0]) != 0:
            continue
        if int(actuator.trnid[0]) != body.joint_index[joint]:
            continue
        out[name] = float(actuator.gainprm[0]) * float(actuator.gear[0])
    return out


def _travel(joint, seconds=0.3):
    """Run the flexors of one joint at full recruitment and report the excursion."""
    body = TwinBody()
    loop = BehaviourLoop(body)
    loop.settle()
    # Lift the animal clear of the floor: on the ground the claw is held by the
    # contact and the joint measures the contact, not the muscle.
    body.data.qpos[2] += 0.5
    mujoco.mj_forward(body.model, body.data)
    flexors = {name: 1.0 for name, torque in _actuators(body, joint).items() if torque < 0}
    assert flexors, "joint %s has no flexor" % joint
    before = float(body.data.qpos[body.qpos_index[joint]])
    for _ in range(int(seconds * 1000)):
        body.set_commands(flexors)
        body.step(0.001)
    after = float(body.data.qpos[body.qpos_index[joint]])
    low, high = [float(value) for value in body.model.jnt_range[body.joint_index[joint]]]
    return abs(after - before), abs(high - low)


@pytest.mark.parametrize("joint", TARSAL)
def test_every_tarsal_joint_has_an_antagonistic_pair(joint):
    """A hinge with one muscle cannot return; with none it cannot move at all."""
    torques = _actuators(TwinBody(), joint)
    assert len(torques) == 2, "%s has %d actuators: %s" % (joint, len(torques), sorted(torques))
    signs = sorted(1 if torque > 0 else -1 for torque in torques.values())
    assert signs == [-1, 1], "%s is not antagonistic: %s" % (joint, torques)


@pytest.mark.parametrize("joint", MOUTH)
def test_every_mouthpart_and_antenna_joint_has_an_antagonistic_pair(joint):
    torques = _actuators(TwinBody(), joint)
    assert len(torques) == 2, "%s has %d actuators: %s" % (joint, len(torques), sorted(torques))
    signs = sorted(1 if torque > 0 else -1 for torque in torques.values())
    assert signs == [-1, 1], "%s is not antagonistic: %s" % (joint, torques)


@pytest.mark.parametrize("joint", ["tarsus_T1_left", "tarsus2_T1_left",
                                   "tarsus3_T1_left", "tarsus4_T1_left",
                                   "tarsus5_T1_left", "labrum_left", "antenna_left"])
def test_a_commanded_joint_covers_a_measurable_part_of_its_travel(joint):
    """The measured floor: the tarsal chain reaches 5.5 to 11 percent of its range."""
    moved, span = _travel(joint)
    assert moved > 0.02 * span, "%s moved %.5f rad, %.1f percent of its %.3f rad range" % (
        joint, moved, 100.0 * moved / span, span)


def test_the_tarsal_chain_curls_the_claw_towards_the_body():
    """Driving all five segments must move the claw, not just rattle the joints."""
    body = TwinBody()
    loop = BehaviourLoop(body)
    loop.settle()
    body.data.qpos[2] += 0.5
    mujoco.mj_forward(body.model, body.data)
    claw = mujoco.mj_name2id(body.model, mujoco.mjtObj.mjOBJ_BODY, "claw_T1_left")
    before = body.data.xpos[claw].copy()
    flexors = {name: 1.0 for name in body.muscles.muscles
               if name.startswith("tarsus") and name.endswith("_flexor")}
    assert len(flexors) == 30, "expected 30 tarsal flexors, found %d" % len(flexors)
    for _ in range(400):
        body.set_commands(flexors)
        body.step(0.001)
    after = body.data.xpos[claw].copy()
    moved_mm = float(np.linalg.norm(after - before)) * 10.0
    assert moved_mm > 1.0, "the claw moved %.3f mm when the whole chain curled" % moved_mm
