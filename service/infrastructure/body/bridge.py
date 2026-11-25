"""Turn a spike raster into muscle commands that persist for a twitch.

A motor neuron fires on a 1 ms grid and a muscle twitch lasts several
milliseconds, so a command that lives for exactly one tick moves nothing.  The
bridge keeps one decaying command per muscle and adds spikes on top of it, which
is what makes a burst of spikes a contraction rather than a click.
"""

from __future__ import annotations

# A twitch in the model decays over this time constant.  It is the same 5 ms the
# muscle actuator uses for its activation filter, so the two do not fight.
TWITCH_DECAY_S = 0.005
# One spike raises the command by this much.  At the measured burst firing (one to
# three spikes in a few milliseconds) a single motor neuron therefore reaches
# roughly a fifth to a half of full recruitment.
SPIKE_GAIN = 0.20


class SpikeDrive:
    """Per-muscle command that spikes raise and time relaxes."""

    def __init__(self, body, *, gain=SPIKE_GAIN, decay_s=TWITCH_DECAY_S):
        self.body = body
        self.gain = float(gain)
        self.decay_s = float(decay_s)
        self.level = {name: 0.0 for name in body.muscles.order}
        self.spikes_seen = 0

    def advance(self, dt_s, spikes=None):
        """Relax every command, then add whatever fired in this tick."""
        factor = 0.0 if self.decay_s <= 0 else pow(2.718281828459045, -dt_s / self.decay_s)
        for name in self.level:
            self.level[name] *= factor
        if spikes:
            for name, value in self.body.command_from_spikes(spikes, gain=self.gain).items():
                if value:
                    self.level[name] = min(1.0, self.level[name] + value)
            self.spikes_seen += sum(int(v) for v in spikes.values())
        return self.level

    def commands(self):
        return dict(self.level)

    def reset(self):
        for name in self.level:
            self.level[name] = 0.0
        self.spikes_seen = 0
