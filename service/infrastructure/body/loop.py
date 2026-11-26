"""One closed loop: a walking fly whose muscles also listen to the connectome.

The loop has three layers, kept apart on purpose so that a measurement can say
which one produced a movement:

  * the gait, the twin's own locomotion programme, which needs no connectome at
    all -- it is what makes the animal walk when nothing hurts;
  * the posture loop, which turns joint targets into muscle recruitment and holds
    the body up against gravity;
  * the connectome, which adds recruitment on top of both and is the only layer
    that carries the stimulus.

Nothing here claims the gait is Drosophila locomotion: it is a tripod pattern
with measured joint signs, and the asset README says so.
"""

from __future__ import annotations

from .bridge import SpikeDrive
from .control import Posture
from .footgait import Escape, FootGait, blend

# The passive springs the model inherits are stiff enough to carry the body and
# stiff enough to swallow most of a muscle's excursion.  At 0.4 the body still
# stands within 0.05 mm of its pose while a single muscle moves its joint 1.8
# times further; the trade is measured in .work/twin/dbg5.py.
COMPLIANCE = 1.0
# The walking configuration, measured rather than chosen: at these values the twin
# covers 32.1 mm in 3 s (10.7 mm/s, the low end of a real fly's 10-30 mm/s) while the
# root height stays inside 0.05 cm, and it does so on every seed tried. Every
# neighbouring point fails: height_gain 6.0 climbs 9.6 cm in 3 s, kp 200 with
# compliance 0.4 covers 1.7 mm in the same time, kp 40 walks backwards
# (.work/twin/walkgrid.py, .work/twin/confirm1.py).
WALK_KP = 60.0
WALK_KD = 4.0
WALK_HEIGHT_GAIN = 0.0
WALK_COMPLIANCE = 1.0
# IK costs six solves of forty iterations, so it is asked every few milliseconds
# and the posture loop interpolates the joint targets in between.
IK_PERIOD_MS = 5


class BehaviourLoop:
    """A walking fly whose muscles also listen to the connectome."""

    def __init__(self, body, *, kp=WALK_KP, kd=WALK_KD, height_gain=WALK_HEIGHT_GAIN,
                 compliance=WALK_COMPLIANCE, period_s=0.18, stroke_cm=0.22,
                 lift_cm=0.02, sway_cm=0.004, escape_threshold=1):
        self.body = body
        # The claws need a tangential contact model before anything can push: with
        # the source model's condim 1 the twin walks backwards at 0.56 mm/s, with
        # condim 3 and friction 4.0 it walks forwards at 10.7 mm/s (.work/twin/confirm1.py).
        if hasattr(body, "set_claw_grip"):
            body.set_claw_grip()
        self.apply_compliance(compliance)
        self.posture = Posture(body, kp=kp, kd=kd, height_gain=height_gain)
        self.gait = FootGait(body, period_s=period_s, stroke_cm=stroke_cm,
                             lift_cm=lift_cm, sway_cm=sway_cm,
                             press_cm=0.0)
        self.escape = Escape()
        self.posture.capture_pose()
        self.gait.capture()
        self.joints = self._joints()
        self._mapped = {int(n) for ids in body.mapping.values() for n in ids}
        self.drive = SpikeDrive(body)
        self.time_ms = 0.0
        self.next_ik_ms = 0.0
        # The connectome does not hold a muscle for 350 ms; it decides.  A burst on
        # mapped motor neurons above this count starts the escape programme and
        # records the latency, which is what the dataset needs to label.
        self.escape_threshold = int(escape_threshold)
        self.escape_latency_ms = None
        self.motor_spikes = 0
        self.mapped_first_tick_ms = None

    def _joints(self):
        bounds = ("T1_left", "T1_right", "T2_left", "T2_right", "T3_left", "T3_right")
        return [name for name in self.body.joint_index
                if any(name.endswith(suffix) for suffix in bounds) or name.startswith("abdomen")]

    def apply_compliance(self, scale):
        """Scale the passive joint springs, which decides how far a muscle can move.

        The scale is applied to the stiffness the model shipped with, not to whatever
        the previous call left behind: two loops built on one body used to compound
        the factor (1.0 then 0.4 then 0.16), which silently made every later
        measurement depend on how many loops had been built before it. Measured in
        .work/twin/stand2.py: compliance 0.4 and 1.0 produced identical trajectories.
        """
        # The baseline lives on the body, not on the loop: several loops are built
        # over one body during a sweep, and a per-loop baseline would still read the
        # previous loop's scaled value.
        if not hasattr(self.body, "_stiffness0"):
            self.body._stiffness0 = {
                name: float(self.body.model.jnt_stiffness[self.body.joint_index[name]])
                for name in self._joints()}
        for name, base in self.body._stiffness0.items():
            index = self.body.joint_index[name]
            self.body.model.jnt_stiffness[index] = base * float(scale)
        return float(scale)

    def trigger_escape(self, *, side=0.0, delay_s=None, stride_scale=2.0):
        """Start the escape response; deciding that a stimulus was noxious is the caller's job."""
        self.escape.trigger(side=side, delay_s=12.0 * 1e-3 if delay_s is None else delay_s)
        self.gait.stride_scale = float(stride_scale)
        return self.escape.envelope()

    def settle(self, steps=300, dt_s=0.001):
        """Stand still, then take the stance as the gait reference.

        The gait is defined in foot space, so it has to know where the claws are
        when the animal is standing.  Capturing them before the body settles puts
        every target a fraction of a millimetre above the floor, and a foot that
        never touches the floor cannot push the body anywhere: measured in
        .work/twin/swing.py, the swing and stance claws both sat 0.05-0.29 mm above
        the ground and only three of six touched it.
        """
        for _ in range(steps):
            self.posture.step(dt_s)
        # Settling advances the clock, so the clock is rewound here: otherwise a burst
        # at 3 ms arrives six seconds into the recording and the escape latency is
        # reported as 6612 ms instead of 9 ms.
        self.time_ms = 0.0
        self.next_ik_ms = 0.0
        # Only the feet are re-captured.  capture_pose would also reset the
        # reference height to wherever the body has sunk to, which switches the
        # height reflex off exactly when it is needed: measured in
        # .work/twin/sweep1.py, the twin then sat on its rostrum at -0.06 cm.
        self.gait.capture()
        return self.body.state()

    def reset(self):
        """Put body and programme back to the standing pose, so episodes do not leak.

        Without this a corpus is a single walk with stimuli sprinkled into it: the
        root keeps moving, the abdomen keeps its curl and an escape stays triggered.
        """
        self.body.reset()
        self.escape = Escape()
        self.drive.reset()
        self.time_ms = 0.0
        self.next_ik_ms = 0.0
        self.escape_latency_ms = None
        self.motor_spikes = 0
        self.mapped_first_tick_ms = None
        self.posture.capture_pose()
        self.gait.capture()
        return self.body.state()

    def advance(self, dt_s=0.001, spikes=None, *, gain=0.35):
        """One control period: gait, escape, posture, then connectome recruitment."""
        self.time_ms += dt_s * 1000.0
        self.escape.advance(dt_s)
        # A walk longer than one stroke would otherwise run the legs out of reach: the
        # foot targets are expressed in a frame that travels with the body, and that
        # frame has to be moved forward periodically. Measured without it in
        # .work/twin/valbody.py: 0.006 cm to 4.87 cm, the fly climbing its own legs.
        self.gait.rebase()
        self.gait.advance(dt_s, stride_scale=self.escape.stride_scale())
        if self.time_ms >= self.next_ik_ms:
            self.posture.set_targets(blend(self.gait.joint_targets(),
                                          self.escape.joint_targets(self.joints)))
            self.next_ik_ms = self.time_ms + IK_PERIOD_MS
        commands = self.posture.commands()
        if spikes:
            self.drive.advance(dt_s, spikes)
            for name, value in self.drive.commands().items():
                if value:
                    commands[name] = min(1.0, commands[name] + value)
            # "motor_spikes" used to add up EVERY spike in the raster, including the
            # sensory and interneuronal ones no muscle listens to, and the receipt then
            # read as if 1250 motor neurons had fired. Measured in .work/twin/hyp3.py:
            # of 1250 spikes at -3600 nA only 11 land on a mapped neuron, and at -4800
            # 18 of 1612. The count below is the one the body can actually feel.
            mapped = 0
            for neuron, count in spikes.items():
                if int(neuron) in self._mapped:
                    mapped += int(count)
            self.motor_spikes += mapped
            self.mapped_first_tick_ms = (self.time_ms if self.mapped_first_tick_ms is None
                                         and mapped else self.mapped_first_tick_ms)
            if (mapped >= self.escape_threshold and self.escape_latency_ms is None
                    and not self.escape.active):
                self.trigger_escape()
                self.escape_latency_ms = self.time_ms
        else:
            self.drive.advance(dt_s)
        self.body.set_commands(commands)
        return self.body.step(dt_s)

    def run(self, duration_s, *, spikes_at=None, dt_s=0.001, on_step=None):
        """Run model time; ``spikes_at`` maps a millisecond to a neuron -> count dict."""
        spikes_at = spikes_at or {}
        samples = int(round(duration_s / dt_s))
        trajectory = []
        for index in range(samples):
            tick = int(round((index + 1) * dt_s * 1000.0))
            state = self.advance(dt_s, spikes_at.get(tick))
            state["t_s"] = (index + 1) * dt_s
            state["escape"] = round(float(self.escape.envelope()), 4)
            trajectory.append(state)
            if on_step is not None:
                on_step(index, state)
        return trajectory
