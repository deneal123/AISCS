"""Drive the twin body from motor neuron spikes.

The physics and the connectome meet here and nowhere else: the connectome decides
which neurons fire, this module turns those spikes into muscle recruitment, and
MuJoCo turns recruitment into motion.  Keeping the bridge in one file means the
claim "the body moves because these cells fired" can be checked by reading one
module instead of tracing the whole pipeline.

Units are the twin's: centimetre, gram, second, dyne.  The fly weighs 0.966 dyne.
"""

from __future__ import annotations

import math
import os

from .kinematics import LEGS
from .motors import build_map, recruitment
from .muscles import MuscleSet, VMAX_LENGTHS_PER_S

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MODEL_PATH = os.path.join(ASSET_DIR, "flybody-muscled.xml")
MUSCLES_PATH = os.path.join(ASSET_DIR, "flybody-muscles.json")
# The inventories the map is built from ship with the module: a caller that only
# wants a body that moves must not have to find the frontend assets first.
LEG_INVENTORY_PATH = os.path.join(ASSET_DIR, "motor.json")
ABDOMINAL_INVENTORY_PATH = os.path.join(ASSET_DIR, "abdominal-motors.json")
WING_INVENTORY_PATH = os.path.join(ASSET_DIR, "wing-motors.json")
# Fallback floor height, used only when the model cannot report where its own claws
# are.  A plane at the wrong height is not a cosmetic detail: the animal falls until
# something else carries it, and .work/twin/clawtest.py caught the twin doing exactly
# that -- the claws of the design pose hang at -0.1204..-0.1235 cm while a plane at
# -0.1345 cm sat 0.3-1.2 mm below them, so six claws touched nothing and the rostrum
# and thorax carried the whole weight.
FLOOR_Z = -0.1235
# Claw contact model: condim 3 carries tangential friction, condim 1 does not.
CLAW_CONDIM = 3
CLAW_FRICTION = (4.0, 0.005, 0.0001)
# The source model drives every joint through the same servo, and for a leg that is
# right: a leg moves slowly and holds a pose.  A wing is not a leg.  Measured in
# .work/twin/wgear.py at 200 Hz, the shipped gear reaches 27 degrees of stroke on the
# yaw hinge, and a Drosophila stroke is 140 degrees peak to peak; at 30 times the gear
# the same command reaches 83 degrees on yaw and 189 on pitch.  The factor is applied
# to the wing and haltere actuators only, and only because the flight programme drives
# them as a resonator rather than as a posture.
WING_GEAR_SCALE = 30.0
WING_ACTUATOR_PREFIXES = ("wing_", "haltere_")
# How much stroke one unit of actuator command produces on the yaw hinge at 200 Hz,
# radian peak to peak, measured in the same probe.  The flight programme needs the
# inverse to ask for a stroke in radians.
WING_STROKE_PER_UNIT_RAD = 1.441


class TwinBody:
    """A fly body in MuJoCo, driven by muscle recruitment.

    The class owns three things that must stay consistent: the compiled model, the
    muscle set with its activation state, and the map from neuron to muscle.  It
    does not own the connectome and it does not decide when a stimulus happens;
    it is handed spikes and it reports where the body went.
    """

    def __init__(self, *, model_path=MODEL_PATH, muscles_path=MUSCLES_PATH,
                 leg_inventory=LEG_INVENTORY_PATH,
                 abdominal_inventory=ABDOMINAL_INVENTORY_PATH,
                 wing_inventory=WING_INVENTORY_PATH, floor_z=None):
        try:
            import mujoco
        except ImportError as error:  # pragma: no cover - environment guard
            raise RuntimeError("The twin needs MuJoCo; install it with pip install mujoco==3.3.7") from error
        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.muscles = MuscleSet.load(muscles_path)
        self.mapping, self.unmapped = build_map(leg_inventory, abdominal_inventory,
                                                     wing_inventory)
        self.actuator_index = {}
        for index in range(self.model.nu):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, index)
            if name:
                self.actuator_index[name] = index
        self.wing_actuators = {}
        for name, index in self.actuator_index.items():
            if name.startswith(WING_ACTUATOR_PREFIXES):
                self.model.actuator_gear[index][0] *= WING_GEAR_SCALE
                self.wing_actuators[name] = index
        # Aerodynamic force and the wingbeat both bypass the muscle loop, so they are
        # held here and applied inside step() rather than through set_commands().
        self.beat = {}
        self.external_force = None
        self.steering_torque = 0.0
        self._was_applying = False
        self.thorax_body = int(mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "thorax"))
        self.joint_index = {}
        self.dof_index = {}
        self.qpos_index = {}
        for index in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, index)
            if not name:
                continue
            self.joint_index[name] = index
            self.qpos_index[name] = int(self.model.jnt_qposadr[index])
            self.dof_index[name] = int(self.model.jnt_dofadr[index])
        self.muscle_actuators = {}
        missing = []
        for name in self.muscles.order:
            index = self.actuator_index.get(name)
            if index is None:
                missing.append(name)
            else:
                self.muscle_actuators[name] = index
        if missing:
            raise ValueError("Model has no actuator for %d muscles (%s)" % (len(missing), missing[:3]))
        self.commands = {name: 0. for name in self.muscles.order}
        self.floor_z = self.rest_floor_z() if floor_z is None else float(floor_z)
        self.apply_floor()
        self.reset()

    # -- state -------------------------------------------------------------

    def rest_floor_z(self):
        """The floor that puts the plane exactly under the claws of the design pose.

        The claws are the only part of the model that is supposed to touch the
        ground, so where they hang in qpos0 is the one defensible choice of floor
        height.  Anything lower lets the animal drop onto its thorax or abdomen and
        any controller built on top of that measures the wrong contact set.
        """
        mujoco = self.mujoco
        saved = self.data.qpos.copy()
        self.data.qpos[:] = self.model.qpos0
        mujoco.mj_forward(self.model, self.data)
        lowest = None
        for leg in LEGS:
            body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "claw_%s" % leg)
            if body_id < 0:
                continue
            height = float(self.data.xpos[body_id][2])
            lowest = height if lowest is None else min(lowest, height)
        self.data.qpos[:] = saved
        mujoco.mj_forward(self.model, self.data)
        return FLOOR_Z if lowest is None else lowest

    def apply_floor(self, floor_z=None):
        """Put the ground where the claws are, which is the whole difference between standing and sitting.

        The source model has no floor at all and its claws hang below the body, so a
        plane placed by hand at any other height lets the animal fall until the
        abdomen carries it.  Moving the plane is therefore not a cosmetic choice: it
        decides which part of the body is load bearing.
        """
        if floor_z is not None:
            self.floor_z = float(floor_z)
        index = None
        for geom in range(self.model.ngeom):
            if self.model.geom_type[geom] == self.mujoco.mjtGeom.mjGEOM_PLANE:
                index = geom
                break
        if index is None:
            raise ValueError("The twin model has no floor plane")
        self.model.geom_pos[index][2] = float(self.floor_z)
        return float(self.floor_z)

    def set_claw_grip(self, *, condim=CLAW_CONDIM, friction=CLAW_FRICTION):
        """Give the claws a contact model that can transmit a horizontal push.

        The source model gives the claws condim 1: a contact that resists being
        pressed into the floor and nothing else. A foot with no tangential friction
        cannot hold a stance, so every step slides and the body never travels: measured
        in .work/twin/fric1.py, condim 1 walked -0.044 mm in 2 s while condim 3 with
        friction 4.0 walked +0.081 mm, and in .work/twin/confirm1.py the same
        difference is 0.56 mm/s against 10.69 mm/s. The values are a measured choice,
        not a material constant of fly cuticle.
        """
        mujoco = self.mujoco
        count = 0
        for geom in range(self.model.ngeom):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY,
                                     int(self.model.geom_bodyid[geom])) or ""
            if not name.startswith("claw"):
                continue
            self.model.geom_condim[geom] = int(condim)
            self.model.geom_friction[geom] = list(friction)
            count += 1
        return count

    def reset(self, *, height_cm=None):
        """Put the body in its standing pose with the root on the floor."""
        self.mujoco.mj_resetData(self.model, self.data)
        self.beat = {}
        self.external_force = None
        self.steering_torque = 0.0
        for name in self.muscles.order:
            self.muscles.muscles[name].activation = 0.
        self.commands = {name: 0. for name in self.muscles.order}
        self.data.qpos[:] = self.model.qpos0
        if height_cm is not None:
            self.data.qpos[2] = height_cm
        self.mujoco.mj_forward(self.model, self.data)
        return self.state()

    def state(self):
        """Root position, orientation and velocity, in cm and rad."""
        return {
            "position_cm": [float(x) for x in self.data.qpos[:3]],
            "quaternion_wxyz": [float(x) for x in self.data.qpos[3:7]],
            "velocity_cm_s": [float(x) for x in self.data.qvel[:3]],
            "contacts": int(self.data.ncon),
        }

    def muscle_geometry(self):
        """Length and speed of each joint's muscle, in cm and cm/s.

        A muscle crosses its joint at a fixed moment arm, so its length follows the
        joint angle: l = l0 - arm * sin(theta).  The same relationship placed the
        actuator in the model, so the length fed to the force-length factor belongs
        to the actuator the physics is actually applying.
        """
        lengths = {}
        speeds = {}
        for name in self.muscles.order:
            muscle = self.muscles.muscles[name]
            qpos = self.qpos_index.get(muscle.joint)
            dof = self.dof_index.get(muscle.joint)
            if qpos is None or dof is None:
                lengths[muscle.joint] = muscle.rest_length_cm
                speeds[muscle.joint] = 0.
                continue
            angle = float(self.data.qpos[qpos])
            rate = float(self.data.qvel[dof])
            lengths[muscle.joint] = max(1e-6, muscle.rest_length_cm - muscle.arm_cm * math.sin(angle))
            speeds[muscle.joint] = -muscle.arm_cm * math.cos(angle) * rate
        return lengths, speeds

    # -- flight ------------------------------------------------------------

    def set_beat(self, values):
        """Set wing and haltere actuator commands directly, bypassing the muscle loop.

        The beat is a resonator, not a posture: at 200 Hz a muscle that took 5 ms to
        activate would lag the stroke by a whole period, so the thorax is driven as
        the oscillator it is and the connectome only sets the gain (see flight.py).
        """
        self.beat = {name: float(value) for name, value in values.items()}

    def apply_aerodynamic_force(self, lift_dyne, forward_dyne=0.0):
        """Push the thorax with the force the wings make, dyne, in the body frame.

        MuJoCo has no air, so the force is added here.  Only the mean is applied: the
        fore and aft halves of a stroke carry equal and opposite drag and cancel, so a
        symmetric beat loads the body with lift and nothing else.
        """
        if self.thorax_body < 0:
            return None
        self.external_force = (float(lift_dyne), float(forward_dyne))
        return self.external_force

    def apply_steering_torque(self, dyne_cm):
        """Yaw the whole body with the moment the legs would make, dyne times cm.

        Kept for experiments that want the physical moment; the gait does not use it.
        A turning fly swings the planted claws one way and the body the other, and those
        claws are clamped in this model, so the moment is absorbed as slip and never
        turns the animal: measured in .work/twin/tw1.log, 0.002 to 0.04 dyne cm leaves
        the heading at 3-4 degrees whichever way the animal is told to turn, and 0.08
        upwards tears the feet loose.  A positive moment turns the animal to its left.
        """
        self.steering_torque = float(dyne_cm)
        return self.steering_torque

    def rotate_heading(self, delta_rad):
        """Turn the whole animal about the vertical axis through its own thorax.

        The heading is prescribed, not produced: see the note on TURN_RATE_RAD_S in
        footgait.  Rotating the free joint is the only way to turn a body whose claws are
        clamped to fixed points, because a moment applied to it is absorbed by those
        clamps.  Angular velocity is cleared with it so the rotation does not carry on
        after the steering stops.  Returns the rotation actually applied.
        """
        delta = float(delta_rad)
        if not delta:
            return 0.0
        half = 0.5 * delta
        c, s = math.cos(half), math.sin(half)
        w, x, y, z = [float(v) for v in self.data.qpos[3:7]]
        # q_yaw * q, rotating the body in the world frame rather than about its own axis.
        self.data.qpos[3] = c * w - s * z
        self.data.qpos[4] = c * x - s * y
        self.data.qpos[5] = c * y + s * x
        self.data.qpos[6] = c * z + s * w
        self.data.qvel[3:6] = 0.0
        self.mujoco.mj_forward(self.model, self.data)
        return delta

    # -- control -----------------------------------------------------------

    def command_from_spikes(self, spikes, *, gain=0.05):
        """Recruitment per muscle from a dict of neuron id -> spike count."""
        commands = {}
        for name in self.muscles.order:
            neurons = self.mapping.get(name, ())
            commands[name] = recruitment(spikes, neurons, gain=gain) if neurons else 0.
        return commands

    def set_commands(self, commands):
        self.commands = {name: float(commands.get(name, 0.)) for name in self.muscles.order}

    def step(self, dt_s=None):
        """Advance the physics by one control period, applying the muscle law.

        The physics step is 0.1 ms and a motor neuron fires on a 1 ms grid, so one
        call runs several physics steps and updates the muscle state once per
        control period.  That keeps activation a smooth 5 ms lag instead of a
        per-physics-step jitter.
        """
        dt_s = float(self.model.opt.timestep) if dt_s is None else float(dt_s)
        substeps = max(1, int(round(dt_s / float(self.model.opt.timestep))))
        self.muscles.advance(self.commands, dt_s)
        lengths, speeds = self.muscle_geometry()
        for name, index in self.muscle_actuators.items():
            muscle = self.muscles.muscles[name]
            length = lengths.get(muscle.joint, muscle.rest_length_cm)
            speed = speeds.get(muscle.joint, 0.)
            # The actuator is linear in its control, so the Hill factors, the series
            # element and the moment arm are folded into the control.  Force and the
            # nominal arm already live in the model, in the actuator's gain and gear,
            # so they are not applied twice; the arm profile is a scale around that
            # nominal arm and is the only new factor.
            factor = max(0., muscle.relative_force(length, speed))
            qpos = self.qpos_index.get(muscle.joint)
            angle = float(self.data.qpos[qpos]) if qpos is not None else 0.
            self.data.ctrl[index] = min(
                1., max(0., muscle.series * factor * muscle.arm_scale(angle)))
        for name, value in self.beat.items():
            index = self.actuator_index.get(name)
            if index is not None:
                self.data.ctrl[index] = min(1., max(0., float(value)))
        applying = self.external_force is not None or bool(self.steering_torque)
        lift, forward = self.external_force or (0.0, 0.0)
        if applying or self._was_applying:
            # Applied every substep: MuJoCo clears xfrc_applied at the end of mj_step,
            # so a force set once would act for 0.1 ms and vanish.  The zero case is
            # written too: a torque left in the slot from the previous control period is
            # otherwise latched, and a latching calibration measured a steady 10 degrees
            # turn from a moment that was never actually applied (see .work/twin/tc1.log).
            for _ in range(substeps):
                self.data.xfrc_applied[self.thorax_body][:3] = (forward, 0.0, lift)
                self.data.xfrc_applied[self.thorax_body][5] = self.steering_torque
                self.mujoco.mj_step(self.model, self.data)
            self._was_applying = applying
            return self.state()
        for _ in range(substeps):
            self.mujoco.mj_step(self.model, self.data)
        return self.state()

    def run(self, duration_s, *, spikes=None, dt_s=0.001, on_step=None):
        """Run a stretch of model time, holding recruitment from the given spikes."""
        if spikes is not None:
            self.set_commands(self.command_from_spikes(spikes))
        samples = int(round(duration_s / dt_s))
        trajectory = []
        for index in range(samples):
            state = self.step(dt_s)
            state["t_s"] = (index + 1) * dt_s
            trajectory.append(state)
            if on_step is not None:
                on_step(index, state)
        return trajectory

    def summary(self):
        return {
            "bodies": int(self.model.nbody),
            "joints": int(self.model.njnt),
            "geometries": int(self.model.ngeom),
            "actuators": int(self.model.nu),
            "muscles": len(self.muscles.order),
            "muscles_with_neurons": sum(1 for name in self.muscles.order if self.mapping.get(name)),
            # Unique neurons, not the sum over muscles: one motor neuron usually drives
            # the flexor of a joint and the extensor of its neighbour, so summing counts
            # it several times (630 against 423 real cells, measured in .work/twin/val1.py).
            "neurons_mapped": len({int(n) for ids in self.mapping.values() for n in ids}),
            "neurons_unmapped": len(self.unmapped),
            "timestep_s": float(self.model.opt.timestep),
            "mass_gram": float(self.model.body_mass.sum()),
        }
