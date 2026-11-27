"""A closed loop: the network drives the body and the body drives the network.

Everything before this module ran open loop. The connectome produced a raster, the
raster was turned into muscle recruitment, the body moved, and the network never heard
about it: the same stimulus produced the same raster whether the animal was standing on
its feet or falling off a ledge. Two consequences were measured and both were real -- an
escape could not stop when the animal had already jumped, and a walk could not be
corrected because nothing reported that the ground had tilted.

The loop here is tick by tick, not pass by pass: the LIF graph advances one millisecond,
the body takes one control period, the joint angles the body reached are encoded as
spikes on the proprioceptive cells, and those spikes enter the graph on the next tick
through the same delivery queue a stimulus uses. There is no buffer and no averaging
window, so a change of pose is felt within the two-millisecond synaptic delay the graph
already had.

What is deliberately NOT claimed: the proprioceptive assignment is a proxy (see
proprioception.py), the feedback gain is a modelling choice rather than a measured
transduction, and the network the body talks to is the same uncalibrated LIF graph as
before. What is claimed is narrower and checkable: the body state now reaches the
network, and an episode with the loop closed differs from one with it open.
"""

from __future__ import annotations

import numpy as np

from ..connectome.kernel import advance, signed_weights

# The graph delivers a spike two ticks later, and a cell that has just fired is
# refractory for two ticks; both come from the registered kernel and are repeated here
# only so the loop can say how long a body event takes to be felt.
SYNAPTIC_DELAY_MS = 2
# The kernel gain the stimulus path uses is 0.075 (kernel.py, forced_network.py). The
# loop raises it to 0.15 and says so instead of hiding it: a proprioceptive sheet at
# 0.075 recruits 10 downstream cells against 129 at 0.15, and a bent leg is then
# distinguishable from a still one in 151 cells rather than in none (.work/twin/
# prop11.py). The higher value is a modelling choice, not a measurement, and the
# receipt carries the number so a reader can disagree with it.
LOOP_GAIN = 0.15


class ClosedLoop:
    """The registered LIF graph and the body, advancing together."""

    def __init__(self, graph, *, seed=1, silenced=(), gain=LOOP_GAIN):
        self.graph = graph
        n = int(graph.size)
        self.n = n
        self.voltage = np.random.default_rng(int(seed)).uniform(0, 2, n).astype(np.float32)
        self.current = np.zeros(n, np.float32)
        self.refractory = np.zeros(n, np.int16)
        self.queue = np.zeros((3, n), np.float32)
        self.drive = np.zeros(n, np.float32)
        self.weights = signed_weights(graph.ptr, graph.counts, graph.signs, float(gain))
        self.silenced = np.zeros(n, dtype=np.bool_)
        if silenced:
            positions = np.searchsorted(graph.ids, np.asarray(sorted(int(v) for v in silenced)))
            self.silenced[positions] = True
        self.clock = 0
        self.spikes = []
        self.spike_times = []
        self.body_events = 0

    def push(self, positions):
        """Put events on the delivery queue for the tick after next."""
        slot = (self.clock + SYNAPTIC_DELAY_MS) % 3
        for position in positions:
            start, end = int(self.graph.ptr[position]), int(self.graph.ptr[position + 1])
            np.add.at(self.queue[slot], self.graph.posts[start:end], self.weights[start:end])
        return len(positions)

    def positions_of(self, cell_ids):
        """Graph positions of body ids, dropping any cell the graph does not have."""
        ids = np.asarray(self.graph.ids)
        out = []
        for cell in cell_ids:
            position = int(np.searchsorted(ids, int(cell)))
            if position < len(ids) and int(ids[position]) == int(cell):
                out.append(position)
        return out

    def tick(self):
        """Advance the graph by one millisecond and report which cells fired, by body id."""
        fired = advance(self.graph.ptr, self.graph.posts, self.weights, self.voltage,
                        self.current, self.refractory, self.queue, self.clock,
                        self.drive, 1, self.silenced)
        self.clock += 1
        active = np.flatnonzero(fired).astype(np.int32)
        ids = np.asarray(self.graph.ids)
        if len(active):
            self.spikes.append(active)
            self.spike_times.append(np.full(len(active), self.clock, np.float32))
            return {int(ids[position]): 1 for position in active.tolist()}
        return {}

    def result(self):
        note = ("one tick interleave of the registered LIF graph and the body; "
                "proprioceptive assignment is a proxy")
        return {
            "spike_neurons": np.concatenate(self.spikes) if self.spikes else np.empty(0, np.int32),
            "spike_times_ms": (np.concatenate(self.spike_times) if self.spike_times
                               else np.empty(0, np.float32)),
            "counts": None,
            "body_events": int(self.body_events),
            "metadata": {"loop": "closed", "synaptic_delay_ms": SYNAPTIC_DELAY_MS,
                         "interpretation": note},
        }


def run_closed_loop(graph, *, controller, proprioception, duration_ms,
                    forced=None, source_cells=(), seed=1, on_tick=None,
                    gain=LOOP_GAIN):
    """Run the graph and the body together for ``duration_ms`` ticks.

    ``forced`` maps a tick to a list of body ids to force, which is how the stimulus
    enters; ``source_cells`` are silenced so a forced cell does not additionally
    integrate the network, exactly as run_forced_network does it.
    """
    forced = forced or {}
    loop = ClosedLoop(graph, seed=seed, silenced=source_cells, gain=gain)
    phase = {}
    body_events = 0
    for tick in range(1, int(duration_ms) + 1):
        # Events from the body are computed on the pose reached at the end of the
        # previous tick: the sensor measures the state that exists, not the one
        # commanded.
        events = proprioception.events(tick, 0.001, phase)
        if events:
            positions = loop.positions_of(events)
            body_events += loop.push(positions)
        burst = forced.get(tick)
        if burst:
            loop.push(loop.positions_of(burst))
        spikes = loop.tick()
        controller.advance(0.001, spikes)
        if on_tick is not None:
            on_tick(tick, spikes)
    result = loop.result()
    result["body_events"] = body_events
    return result, controller
