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
# Fallback floor height, used only when the model cannot report where its own claws
# are.  A plane at the wrong height is not a cosmetic detail: the animal falls until
# something else carries it, and .work/twin/clawtest.py caught the twin doing exactly
# that -- the claws of the design pose hang at -0.1204..-0.1235 cm while a plane at
# -0.1345 cm sat 0.3-1.2 mm below them, so six claws touched nothing and the rostrum
# and thorax carried the whole weight.
FLOOR_Z = -0.1235


class TwinBody:
    """A fly body in MuJoCo, driven by muscle recruitment.

    The class owns three things that must stay consistent: the compiled model, the
    muscle set with its activation state, and the map from neuron to muscle.  It
    does not own the connectome and it does not decide when a stimulus happens;
    it is handed spikes and it reports where the body went.
    """

    def __init__(self, *, model_path=MODEL_PATH, muscles_path=MUSCLES_PATH,
                 leg_inventory=LEG_INVENTORY_PATH,
                 abdominal_inventory=ABDOMINAL_INVENTORY_PATH, floor_z=None):
        try:
            import mujoco
        except ImportError as error:  # pragma: no cover - environment guard
            raise RuntimeError("The twin needs MuJoCo; install it with pip install mujoco==3.3.7") from error
        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.muscles = MuscleSet.load(muscles_path)
        self.mapping, self.unmapped = build_map(leg_inventory, abdominal_inventory)
        self.actuator_index = {}
        for index in range(self.model.nu):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, index)
            if name:
                self.actuator_index[name] = index
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

    def reset(self, *, height_cm=None):
        """Put the body in its standing pose with the root on the floor."""
        self.mujoco.mj_resetData(self.model, self.data)
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
            # The actuator is linear in its control, so the Hill factors are folded
            # into the control.  Force and moment arm already live in the model, in
            # the actuator's gain and gear, so they are not applied twice.
            factor = max(0., muscle.relative_force(length, speed))
            self.data.ctrl[index] = min(1., max(0., muscle.activation * factor))
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
            "neurons_mapped": sum(len(ids) for ids in self.mapping.values()),
            "neurons_unmapped": len(self.unmapped),
            "timestep_s": float(self.model.opt.timestep),
            "mass_gram": float(self.model.body_mass.sum()),
        }

