"""Inverse kinematics for one leg: where the foot must be, and the joint angles that put it there.

The gait is defined in foot space, not in joint space. That is the only way to get a
walking insect rather than a leg that waves: a stance foot has to stay put on the
ground while the body moves over it, and a joint-space prescription cannot express
stay put.

The solver is damped least squares on the measured Jacobian. MuJoCo gives the foot
position for a joint vector through forward kinematics, so the Jacobian is measured
rather than derived, and the solution is clipped to the joint ranges the model
declares.

Units are the twin units: centimetre, radian, second.
"""

from __future__ import annotations

import numpy as np

# The seven joints of a leg, in the order the solver returns them.
LEG_JOINTS = (
    "coxa_abduct_{leg}",
    "coxa_twist_{leg}",
    "coxa_{leg}",
    "femur_twist_{leg}",
    "femur_{leg}",
    "tibia_{leg}",
    "tarsus_{leg}",
)
LEGS = ("T1_left", "T1_right", "T2_left", "T2_right", "T3_left", "T3_right")
# How far the foot may be from its goal, cm. Below this the solver stops: the model
# cannot place the claw exactly, and pretending otherwise hides a real limit.
TOLERANCE_CM = 1e-4


class LegKinematics:
    """Forward and inverse kinematics for the six legs of one twin body."""

    def __init__(self, body):
        self.body = body
        self.model = body.model
        self.data = body.data
        self.mujoco = body.mujoco
        self.joints = {}
        self.claws = {}
        self.qpos = {}
        self.low = {}
        self.high = {}
        for leg in LEGS:
            names = [pattern.format(leg=leg) for pattern in LEG_JOINTS]
            missing = [n for n in names if n not in body.qpos_index]
            if missing:
                raise ValueError("Leg %s is missing joints %s" % (leg, missing))
            self.joints[leg] = names
            self.claws[leg] = self.model.body("claw_%s" % leg).id
            self.qpos[leg] = [body.qpos_index[n] for n in names]
            self.low[leg] = np.array([float(self.model.jnt_range[body.joint_index[n]][0])
                                      for n in names])
            self.high[leg] = np.array([float(self.model.jnt_range[body.joint_index[n]][1])
                                       for n in names])

    # -- forward ----------------------------------------------------------

    def angles(self, leg):
        """Current joint angles of the leg."""
        return np.array([float(self.data.qpos[a]) for a in self.qpos[leg]])

    def set_angles(self, leg, angles):
        for address, value in zip(self.qpos[leg], angles):
            self.data.qpos[address] = float(value)
        self.mujoco.mj_forward(self.model, self.data)

    def foot(self, leg, angles=None):
        """Claw position in world coordinates, cm."""
        if angles is not None:
            self.set_angles(leg, angles)
        return np.array([float(v) for v in self.data.xpos[self.claws[leg]]])

    def jacobian(self, leg, angles, eps=1e-4):
        """d(foot)/d(angle), measured by moving each joint a little."""
        base = self.foot(leg, angles)
        matrix = np.zeros((3, len(angles)))
        for index in range(len(angles)):
            shifted = angles.copy()
            shifted[index] += eps
            matrix[:, index] = (self.foot(leg, shifted) - base) / eps
        self.set_angles(leg, angles)
        return matrix

    # -- inverse ----------------------------------------------------------

    def solve(self, leg, target, guess=None, iterations=40, damping=1e-3):
        """Joint angles that put the claw at the target, and the error in cm.

        A large error means the target is out of reach; the caller decides what to do
        about it, because silently returning the closest reachable pose would
        misreport where the foot is."""
        angles = self.angles(leg).copy() if guess is None else np.array(guess, dtype=float)
        target = np.asarray(target, dtype=float)
        for _ in range(iterations):
            error = target - self.foot(leg, angles)
            if float(np.linalg.norm(error)) < TOLERANCE_CM:
                break
            matrix = self.jacobian(leg, angles)
            normal = matrix.T @ matrix + damping * np.eye(len(angles))
            delta = np.linalg.solve(normal, matrix.T @ error)
            angles = np.clip(angles + delta, self.low[leg], self.high[leg])
        final = float(np.linalg.norm(target - self.foot(leg, angles)))
        return angles, final

    def rest_feet(self):
        """Where the claws sit in the model’s own standing pose."""
        saved = {leg: self.angles(leg).copy() for leg in LEGS}
        self.body.reset()
        feet = {leg: self.foot(leg) for leg in LEGS}
        for leg, angles in saved.items():
            self.set_angles(leg, angles)
        return feet
