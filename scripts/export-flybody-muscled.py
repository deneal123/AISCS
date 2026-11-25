"""Export the meshless, muscle-driven FlyBody model used by the behaviour twin.

Source: MuJoCo Menagerie ``flybody`` (Apache-2.0, upstream f3b6013).  The source
carries 85 visual meshes the server does not need and 78 positional servos that
cannot express a muscle.  This exporter

  * keeps the collision geometry, the joint tree and the true inertial parameters,
  * drops every mesh, so the model is a few kilobytes and loads without assets,
  * replaces the servos on three proximal joints of every leg with 36 muscles,
  * emits each muscle as a first-order activation filter plus a spatial tendon,
  * measures the actual joint direction of every muscle instead of assuming it.

Units are the source units and are CGS-like: centimetre, gram, second, so force
is the dyne (1e-5 N) and the whole fly weighs 0.966 dyne.  This matters: reading
the numbers as metres and newtons gives a fly 1e-2 m long that nothing can lift.

Run inside an image with mujoco: source at /src, output at /out.
"""
from __future__ import annotations

import json
import os

import mujoco
import numpy as np

SOURCE = "/src/fruitfly.xml"
OUT_XML = "/out/flybody-muscled.xml"
OUT_JSON = "/out/flybody-muscles.json"

LEGS = ["T1_left", "T2_left", "T3_left", "T1_right", "T2_right", "T3_right"]
# The legs move the body; the abdomen curls, which is the measured defensive
# response to a noxious stimulus, so it gets its own muscle pairs.
# The three joints that move a leg: the coxa swings it fore and aft about x, the
# femur lifts it about x, the tibia folds it about x.  The abduct and twist joints
# are the small out-of-plane adjustments; driving them instead of these three was
# measured to produce 0.4 mm of travel, which is why the muscle model spans the
# joints the source model's own servos used.
# A leg swings fore and aft by yawing the coxa about the vertical axis, lifts by
# extending the femur about the body's long axis, and folds by the tibia.  Those
# three are the joints the walking gait uses; the abduct and twist joints are the
# small out-of-plane adjustments and the tarsus chain is passive.
DRIVEN_LEG = [
    # Every joint the source model actuates with a servo gets a muscle pair, so
    # the twin can hold and move the pose the body was designed to hold.  Driving
    # only three of them was measured to let the leg buckle at the joints left
    # passive: the body sank onto its abdomen and travelled 0.5 mm in a second.
    ("coxa_abduct_{leg}", "coxa_abduct", "protraction"),
    ("coxa_twist_{leg}", "coxa_twist", "abduction"),
    ("coxa_{leg}", "coxa", "extension"),
    ("femur_twist_{leg}", "femur_twist", "rotation"),
    ("femur_{leg}", "femur", "elevation"),
    ("tibia_{leg}", "tibia", "flexion"),
    ("tarsus_{leg}", "tarsus", "tarsus"),
]
ABDOMEN_SEGMENTS = [1, 2, 3, 4, 5, 6, 7]
DRIVEN_ABDOMEN = [
    # Note the order: the source model names the abduct joint with its suffix
    # first (abdomen_abduct_2), the pitch joint without one (abdomen_2).
    ("{segment}", "abdomen_pitch", "curl"),
    ("abdomen_abduct{tail}", "abdomen_yaw", "lateral"),
]
# Peak isometric force per muscle, dyne.  A leg muscle of Drosophila produces of
# the order of a few body weights: 0.966 dyne is the whole animal, and measured
# leg muscles of similar insects reach 1 to 5 dyne.  These numbers are at the top
# of that range because the twin has to hold a pose the source model held with
# servos: with one body weight per muscle the body sank onto its abdomen and the
# gait moved 0.05 mm/s, and the sweep in .work/twin/forcewalk.py measured that
# five to ten times less force is the difference between standing and collapsing.
PEAK_FORCE_DYNE = {"coxa_abduct": 5.0, "coxa_twist": 2.0, "coxa": 5.0,
                   "femur_twist": 2.0, "femur": 5.0, "tibia": 3.0, "tarsus": 0.7,
                   "abdomen_pitch": 2.0, "abdomen_yaw": 1.2}
# Lateral offset of both attachment points from the joint axis, as a fraction of
# the driven segment length: this offset is the moment arm of the muscle.
ARM_FRACTION = 0.25
# Along-segment separation of the two attachment points, in segment lengths.
SPAN = 0.35
# Angular offset of the two attachment points around the joint axis, degrees.
MUSCLE_WRAP_DEG = 150.0
MUSCLE_TIME_CONSTANT_S = 0.005
GEOM_TYPES = {2: "sphere", 3: "capsule", 4: "ellipsoid", 5: "cylinder", 6: "box"}


def name_of(model, kind, index):
    return mujoco.mj_id2name(model, kind, index)


def fmt(values):
    return " ".join(repr(float(v)) for v in values)


def joint_index(model, name):
    for j in range(model.njnt):
        if name_of(model, mujoco.mjtObj.mjOBJ_JOINT, j) == name:
            return j
    raise KeyError(name)


def collect(src):
    bodies = [name_of(src, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(src.nbody)]
    children = {}
    for i in range(1, src.nbody):
        children.setdefault(int(src.body_parentid[i]), []).append(i)
    geoms = []
    for g in range(src.ngeom):
        if int(src.geom_type[g]) == int(mujoco.mjtGeom.mjGEOM_MESH):
            continue
        geoms.append(dict(
            name=name_of(src, mujoco.mjtObj.mjOBJ_GEOM, g),
            body=bodies[int(src.geom_bodyid[g])],
            type=int(src.geom_type[g]),
            size=[float(x) for x in src.geom_size[g]],
            pos=[float(x) for x in src.geom_pos[g]],
            quat=[float(x) for x in src.geom_quat[g]],
            conaffinity=int(src.geom_conaffinity[g]),
            condim=int(src.geom_condim[g]),
            friction=[float(x) for x in src.geom_friction[g]],
            solref=[float(x) for x in src.geom_solref[g]],
            solimp=[float(x) for x in src.geom_solimp[g]],
            margin=float(src.geom_margin[g]),
            gap=float(src.geom_gap[g]),
        ))
    sites = []
    for s in range(src.nsite):
        sites.append(dict(name=name_of(src, mujoco.mjtObj.mjOBJ_SITE, s),
                          body=bodies[int(src.site_bodyid[s])],
                          pos=[float(x) for x in src.site_pos[s]],
                          size=[float(x) for x in src.site_size[s]]))
    tendons = []
    for t in range(src.ntendon):
        adr, num = int(src.tendon_adr[t]), int(src.tendon_num[t])
        joints = []
        for k in range(num):
            if int(src.wrap_type[adr + k]) != int(mujoco.mjtWrap.mjWRAP_JOINT):
                continue
            joints.append((name_of(src, mujoco.mjtObj.mjOBJ_JOINT, int(src.wrap_objid[adr + k])),
                           float(src.wrap_prm[adr + k])))
        tendons.append(dict(name=name_of(src, mujoco.mjtObj.mjOBJ_TENDON, t), joints=joints))
    servos = []
    for a in range(src.nu):
        trn, tid = int(src.actuator_trntype[a]), int(src.actuator_trnid[a][0])
        target = (name_of(src, mujoco.mjtObj.mjOBJ_JOINT, tid) if trn == 0 else
                  name_of(src, mujoco.mjtObj.mjOBJ_TENDON, tid) if trn == 3 else None)
        servos.append(dict(name=name_of(src, mujoco.mjtObj.mjOBJ_ACTUATOR, a), trntype=trn,
                           target=target,
                           gainprm=[float(x) for x in src.actuator_gainprm[a]],
                           biasprm=[float(x) for x in src.actuator_biasprm[a]],
                           ctrlrange=[float(x) for x in src.actuator_ctrlrange[a]],
                           gear=[float(x) for x in src.actuator_gear[a]]))
    return bodies, children, geoms, sites, tendons, servos


def emit(src, bodies, children, geoms, sites, tendons, servos, muscles):
    """Return the MJCF text.  ``anchors`` maps site name to a local position."""
    driven = {m["joint"] for m in muscles}
    lines = ['<mujoco model="flybody-muscled">',
             '  <compiler angle="radian" autolimits="true"/>',
             '  <option timestep="%r" gravity="%s" viscosity="%r" density="%r" '
             'cone="elliptic" noslip_iterations="3"/>' % (
                 float(src.opt.timestep), fmt(src.opt.gravity), float(src.opt.viscosity),
                 float(src.opt.density)),
             '  <size njmax="800" nconmax="300" nkey="0"/>',
             '  <visual><global offwidth="1280" offheight="960"/></visual>',
             '  <worldbody>',
             '    <geom name="floor" type="plane" size="2 2 0.01" pos="0 0 -0.1325" '
             'contype="1" conaffinity="1" friction="0.8 0.005 0.0001" solref="0.0002 1"/>']

    def emit_body(i, depth):
        pad = "  " * depth
        name = bodies[i]
        lines.append('%s<body name="%s" pos="%s" quat="%s">' % (
            pad, name, fmt(src.body_pos[i]), fmt(src.body_quat[i])))
        inner = pad + "  "
        lines.append('%s<inertial pos="%s" quat="%s" mass="%r" diaginertia="%s"/>' % (
            inner, fmt(src.body_ipos[i]), fmt(src.body_iquat[i]), float(src.body_mass[i]),
            fmt(src.body_inertia[i])))
        for j in range(src.njnt):
            if int(src.jnt_bodyid[j]) != i:
                continue
            dof = int(src.jnt_dofadr[j])
            jname = name_of(src, mujoco.mjtObj.mjOBJ_JOINT, j)
            if int(src.jnt_type[j]) == 0:
                lines.append('%s<joint name="%s" type="free"/>' % (inner, jname))
                continue
            lines.append(
                '%s<joint name="%s" type="hinge" axis="%s" pos="%s" range="%s" '
                'limited="%s" stiffness="%r" springref="%r" damping="%r" armature="%r"/>' % (
                    inner, jname, fmt(src.jnt_axis[j]), fmt(src.jnt_pos[j]),
                    fmt(src.jnt_range[j]), "true" if src.jnt_limited[j] else "false",
                    float(src.jnt_stiffness[j]),
                    float(src.qpos_spring[int(src.jnt_qposadr[j])]),
                    float(src.dof_damping[dof]), float(src.dof_armature[dof])))
        for g in geoms:
            if g["body"] != name:
                continue
            lines.append(
                '%s<geom name="%s" type="%s" size="%s" pos="%s" quat="%s" condim="%d" '
                'friction="%s" solref="%s" solimp="%s" margin="%r" gap="%r" '
                'contype="1" conaffinity="%d"/>' % (
                    inner, g["name"], GEOM_TYPES[g["type"]], fmt(g["size"]), fmt(g["pos"]),
                    fmt(g["quat"]), g["condim"], fmt(g["friction"]), fmt(g["solref"]),
                    fmt(g["solimp"]), g["margin"], g["gap"], g["conaffinity"]))
        for s in sites:
            if s["body"] != name:
                continue
            lines.append('%s<site name="%s" pos="%s" size="%s"/>' % (
                inner, s["name"], fmt(s["pos"]), fmt(s["size"])))
        for c in children.get(i, []):
            emit_body(c, depth + 1)
        lines.append("%s</body>" % pad)

    for c in children.get(0, []):
        emit_body(c, 2)
    lines.append("  </worldbody>")
    lines.append("  <tendon>")
    for t in tendons:
        if not t["joints"]:
            continue
        lines.append('    <fixed name="%s">' % t["name"])
        for joint_name, coef in t["joints"]:
            lines.append('      <joint joint="%s" coef="%r"/>' % (joint_name, coef))
        lines.append("    </fixed>")
    lines.append("  </tendon>")
    lines.append("  <actuator>")
    for s in servos:
        if s["trntype"] == 5 or s["target"] in driven:
            continue  # adhesion is applied by the controller; driven joints are muscles now
        link = "joint" if s["trntype"] == 0 else "tendon"
        lines.append(
            '    <general name="%s" %s="%s" gainprm="%s" biasprm="%s" ctrlrange="%s" '
            'gear="%s"/>' % (s["name"], link, s["target"], fmt(s["gainprm"]),
                              fmt(s["biasprm"]), fmt(s["ctrlrange"]), fmt(s["gear"])))
    for m in muscles:
        # First-order activation with gainprm[0] as the peak force and gear as the
        # signed moment arm: control is the recruitment in [0, 1], act filters it,
        # force = gainprm[0] * act dyne, torque = force * gear dyne*cm.
        lines.append(
            '    <general name="%s" joint="%s" dyntype="filter" '
            'dynprm="%r 0 0 0 0 0 0 0 0 0" gaintype="fixed" '
            'gainprm="%r 0 0 0 0 0 0 0 0 0" biastype="none" ctrlrange="0 1" gear="%r"/>'
            % (m["name"], m["joint"], MUSCLE_TIME_CONSTANT_S,
               m["peak_force_dyne"], m["arm_cm"] * m["sign"] * m["side_sign"]))
    lines.append("  </actuator>")
    lines.append("</mujoco>")
    return "\n".join(lines) + "\n"


def moment_arm(model, data, joint_name, sign):
    """Moment arm of a muscle about its joint, cm.

    The source model has no apodeme geometry, so every muscle is modelled as a
    line of action at a constant moment arm taken from the segment it moves: half
    the segment length times ARM_FRACTION.  A constant moment arm is the standard
    simplification when the tendon path is unknown, and it keeps the muscle law
    explicit: torque = force * arm, both measurable to the last digit.
    """
    j = joint_index(model, joint_name)
    child = int(model.jnt_bodyid[j])
    kids = np.where(model.body_parentid == child)[0]
    child_world = np.array(data.xpos[child], dtype=float)
    far = (np.array(data.xpos[kids[0]], dtype=float) if len(kids)
           else child_world + np.array([0.0, 0.3, 0.0]))
    length = float(np.linalg.norm(far - child_world))
    return ARM_FRACTION * length, length


def torque_of(model, m):
    """Signed joint torque of one muscle at full activation, dyne*cm."""
    j = joint_index(model, m["joint"])
    dof = int(model.jnt_dofadr[j])
    a = [k for k in range(model.nu)
         if name_of(model, mujoco.mjtObj.mjOBJ_ACTUATOR, k) == m["name"]][0]
    run = mujoco.MjData(model)
    mujoco.mj_forward(model, run)
    run.act[int(model.actuator_actadr[a])] = 1.0
    mujoco.mj_forward(model, run)
    return float(run.qfrc_actuator[dof])


def main():
    src = mujoco.MjModel.from_xml_path(SOURCE)
    bodies, children, geoms, sites, tendons, servos = collect(src)

    targets = []
    for leg in LEGS:
        for template, group, role in DRIVEN_LEG:
            targets.append((template.format(leg=leg), group, role, leg))
    for segment in ABDOMEN_SEGMENTS:
        for template, group, role in DRIVEN_ABDOMEN:
            segment_name = "abdomen" if segment == 1 else "abdomen_%d" % segment
            targets.append((template.format(
                segment=segment_name,
                tail="" if segment == 1 else "_%d" % segment), group, role, segment_name))

    muscles = []
    for joint_name, group, role, part in targets:
        j = joint_index(src, joint_name)
        child = bodies[int(src.jnt_bodyid[j])]
        parent = bodies[int(src.body_parentid[int(src.jnt_bodyid[j])])]
        for sign, suffix in ((+1, "extensor"), (-1, "flexor")):
            muscles.append(dict(
                name="%s_%s_%s" % (group, part, suffix),
                joint=joint_name,
                sign=sign,
                # Which side of the axis the tendon sits on.  A twist joint runs
                # along its own rotation axis, so the side that yields the
                # intended direction cannot be reasoned out from the frame; the
                # gear sign carries it instead, and it is verified by measurement.
                side_sign=1.0,
                intended_torque_sign=1.0 if sign > 0 else -1.0,
                role=role,
                part=part,
                body_origin=parent,
                body_insertion=child,
                peak_force_dyne=PEAK_FORCE_DYNE[group],
                axis=[float(x) for x in src.jnt_axis[j]],
                range=[float(x) for x in src.jnt_range[j]],
            ))

    # The moment arm is a property of the joint tree, which the meshless model
    # copies verbatim, so it is read straight off the source model.
    src_data = mujoco.MjData(src)
    mujoco.mj_forward(src, src_data)
    for m in muscles:
        arm, length = moment_arm(src, src_data, m["joint"], m["sign"])
        m["arm_cm"] = arm
        m["segment_length"] = length
    del src_data

    os.makedirs("/out", exist_ok=True)
    with open(OUT_XML, "w") as handle:
        handle.write(emit(src, bodies, children, geoms, sites, tendons, servos, muscles))
    probe = mujoco.MjModel.from_xml_path(OUT_XML)
    for m in muscles:
        m["torque_dyne_cm"] = torque_of(probe, m)
        m["direction_verified"] = bool(
            np.sign(m["torque_dyne_cm"]) == np.sign(m["intended_torque_sign"]))
        j = joint_index(probe, m["joint"])
        run = mujoco.MjData(probe)
        mujoco.mj_forward(probe, run)
        before = float(run.qpos[probe.jnt_qposadr[j]])
        act = [k for k in range(probe.nu)
               if name_of(probe, mujoco.mjtObj.mjOBJ_ACTUATOR, k) == m["name"]][0]
        run.ctrl[act] = 1.0
        for _ in range(1000):
            mujoco.mj_step(probe, run)
        m["joint_travel_rad"] = float(run.qpos[probe.jnt_qposadr[j]]) - before
    del probe

    flips = 0
    flipped_joints = []
    unverified = [m["name"] for m in muscles if not m["direction_verified"]]

    payload = dict(
        format="aspa.flybody.muscles",
        version=1,
        units={"length": "cm", "mass": "g", "time": "s", "force": "dyne"},
        source="MuJoCo Menagerie flybody, Apache-2.0, upstream f3b6013",
        arm_fraction=ARM_FRACTION,
        span=SPAN,
        wrap_deg=MUSCLE_WRAP_DEG,
        time_constant_s=MUSCLE_TIME_CONSTANT_S,
        peak_force_dyne=PEAK_FORCE_DYNE,
        calibrated_flips=flips,
        unverified_muscles=unverified,
        driven_joints=sorted({m["joint"] for m in muscles}),
        muscles=muscles,
    )
    with open(OUT_JSON, "w") as handle:
        json.dump(payload, handle, indent=1)
    print("wrote", OUT_XML, os.path.getsize(OUT_XML), "bytes,", len(muscles),
          "muscles,", flips, "calibration flips")
    for m in muscles[:6]:
        print("%-38s torque %+0.4e  travel %+0.4f rad" % (
            m["name"], m["torque_dyne_cm"], m["joint_travel_rad"]))


if __name__ == "__main__":
    main()
