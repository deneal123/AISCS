"""One episode: a stimulus, a connectome response, a body that moves, a record.

An episode is the unit a pain dataset is made of. It has to hold four things that
were, until now, measured in four different places:

  * what was applied, and where -- the stimulus is a pair (site, current), because the
    nociception series showed that no single cell carries the label;
  * what the connectome did -- spikes per cell and the per-millisecond activity vector,
    which is the only channel that still shows the network when the electrode trace has
    decayed to zero;
  * what the body did -- displacement, abdominal curl, height, and the latency of the
    escape, which is the behavioural readout the twin can actually produce;
  * what the electrode saw -- joined in by the caller that owns a field solve, because
    the twin has no field of its own.

Nothing here decides whether a stimulus hurts. It records what happened so that a
later analysis can decide, and it refuses to write a label of its own.

Units are the twin units: centimetre, radian, second, dyne.
"""

from __future__ import annotations

import json

import numpy as np

# The label vocabulary. A cell is never called a nociceptor on its own: the measured
# fact is that a noxious input reached the ascending layer, and the label says exactly
# that and nothing more.
LABEL_NOXIOUS_INPUT = "noxious_input_arrived"
LABEL_NO_ESCAPE = "no_escape"
LABEL_ESCAPE = "escape"
LABEL_FLIGHT = "flight"
# The format name says noxious, not pain: the record holds what was applied and what
# answered, and naming it after the feeling would claim the conclusion.
FORMAT = "malecns-noxious-episode-v1"


class Episode:
    """The record of one stimulus applied to one body through one connectome."""

    def __init__(self, *, seed, site_um, current_na, source_cells, duration_ms,
                 reason):
        self.seed = int(seed)
        self.site_um = tuple(float(v) for v in site_um)
        self.current_na = float(current_na)
        self.source_cells = sorted(int(c) for c in source_cells)
        self.duration_ms = int(duration_ms)
        self.reason = str(reason)
        self.network = {}
        self.body = {}
        self.electrode = {}
        self.compound = {}
        self.loop = {}

    def record_network(self, *, spikes, spike_neurons, spike_times_ms, activity,
                       cell_ids):
        """Store the raster and the per-millisecond activity the electrode cannot carry."""
        activity = np.asarray(activity, dtype=np.int64)
        if activity.ndim != 1:
            raise ValueError("Invalid activity vector")
        if (activity < 0).any():
            raise ValueError("Invalid negative activity")
        spikes = np.asarray(spikes)
        neurons = np.asarray(spike_neurons)
        times = np.asarray(spike_times_ms)
        if not (len(spikes) == len(neurons) == len(times)):
            raise ValueError("Invalid spike raster")
        order = np.argsort(times, kind="stable")
        active = activity > 0
        self.network = {
            "spike_count": int(len(spikes)),
            "cell_count": int(np.unique(neurons).size),
            "activity_ticks": int(len(activity)),
            "active_ticks": int(np.count_nonzero(activity)),
            "peak_activity": int(activity.max()) if len(activity) else 0,
            "first_active_tick": int(np.argmax(active)) if active.any() else None,
            "last_active_tick": (int(len(activity) - 1 - np.argmax(active[::-1]))
                                 if active.any() else None),
            # The raster is kept as body ids, not positions: a position means nothing
            # outside the graph that produced it.
            "raster": [[int(neurons[i]), int(round(float(times[i])))] for i in order],
            "activity": [int(v) for v in activity],
            "graph_cells": int(len(cell_ids)),
        }
        return self.network

    def record_body(self, *, start, end, curl_start, curl_end, escape_latency_ms,
                    peak_height_cm, min_height_cm, motor_spikes=0,
                    mapped_first_tick_ms=None, flight=None,
                    heading_start_rad=None, turn_deg=None):
        dx = (float(end[0]) - float(start[0])) * 10.0
        dy = (float(end[1]) - float(start[1])) * 10.0
        dz = (float(end[2]) - float(start[2])) * 10.0
        self.body = {
            "displacement_mm": round(float(np.hypot(dx, dy)), 4),
            "displacement_x_mm": round(dx, 4),
            "displacement_z_mm": round(dz, 4),
            "curl_change_rad": round(float(curl_end) - float(curl_start), 5),
            "escape_latency_ms": (None if escape_latency_ms is None
                                  else round(float(escape_latency_ms), 3)),
            "min_height_cm": round(float(min_height_cm), 5),
            "peak_height_cm": round(float(peak_height_cm), 5),
            # Spikes that reached a muscle, not every spike in the raster. The two
            # differ by two orders of magnitude: at -3600 nA the old counter said 1250
            # while 11 reached a muscle (report 38, section 6). The tick is when the
            # first of them landed, so a reader can tell whether the body heard the
            # network before or after the escape programme fired.
            "motor_spikes": int(motor_spikes),
            "mapped_first_tick_ms": (None if mapped_first_tick_ms is None
                                     else round(float(mapped_first_tick_ms), 3)),
            # Which way the animal ended up facing. The displacement above has no sign
            # for it: an escape to the left and one to the right cover the same distance.
            # None rather than zero when the body was not asked, so a reader can tell a
            # straight run from a run that was never measured.
            "heading_start_rad": (None if heading_start_rad is None
                                  else round(float(heading_start_rad), 6)),
            "turn_deg": None if turn_deg is None else round(float(turn_deg), 3),
        }
        # Flight is recorded apart from walking because it is a different claim: a
        # displacement can be walked or flown, and only the beat and the lift say which.
        if flight is not None:
            self.body["flight"] = {
                "latency_ms": (None if flight.get("latency_ms") is None
                               else round(float(flight["latency_ms"]), 3)),
                "wing_spikes": int(flight.get("wing_spikes", 0)),
                "lift_to_weight": round(float(flight.get("lift_to_weight", 0.0)), 4),
                "airborne_cm": round(float(flight.get("airborne_cm", 0.0)), 5),
                "beating": bool(flight.get("beating", False)),
            }
        return self.body

    def record_loop(self, proprioception, *, body_events):
        """What the body said to the network, and what the network made of it.

        An episode that ran open loop leaves this empty; a closed one names the cells
        that carried the pose back, the rate they fired at, and how many events the
        body injected. Without this block a closed episode and an open one differ only
        in their spike counts, which is not an explanation.
        """
        self.loop = {
            "closed": True,
            "body_events": int(body_events),
            "proprioception": dict(proprioception),
        }
        return self.loop

    def record_electrode(self, *, ptp_uv, tail_abs_max_uv, samples, source):
        """The field recording is joined in by whoever owns a field solve."""
        self.electrode = {
            "ptp_uv": round(float(ptp_uv), 4),
            "tail_abs_max_uv": round(float(tail_abs_max_uv), 6),
            "samples": int(samples),
            "source": str(source),
        }
        return self.electrode

    def record_compound_action(self, receipt):
        """The propagating-electrode channel, when the caller built one.

        This is separate from record_electrode on purpose. That block is a field
        solve, which the twin does not own; this block is a forward model of a passing
        volley, which the twin can compute from its own raster. Keeping them apart stops
        a model output from being read as a measurement.
        """
        if not isinstance(receipt, dict) or not receipt.get("format"):
            raise ValueError("Invalid compound action receipt")
        if receipt["format"] != "malecns-compound-action-potential-v1":
            raise ValueError("Unexpected compound action receipt format")
        self.compound = dict(receipt)
        return self.compound

    def labels(self):
        """What may be claimed from this episode, and nothing more."""
        labels = []
        if self.network.get("spike_count", 0) > 0:
            labels.append(LABEL_NOXIOUS_INPUT)
        if self.body.get("escape_latency_ms") is None:
            labels.append(LABEL_NO_ESCAPE)
        else:
            labels.append(LABEL_ESCAPE)
        if self.body.get("flight", {}).get("beating"):
            labels.append(LABEL_FLIGHT)
        return labels

    def record(self):
        return {
            "format": FORMAT,
            "seed": self.seed,
            "site_um": list(self.site_um),
            "current_na": self.current_na,
            "source_cells": self.source_cells,
            "source_cell_count": len(self.source_cells),
            "duration_ms": self.duration_ms,
            "reason": self.reason,
            "network": self.network,
            "body": self.body,
            "electrode": self.electrode,
            "compound_action": self.compound,
            "loop": self.loop,
            "labels": self.labels(),
            # Stated once per record so a reader cannot mistake the label for a
            # statement about a cell.
            "label_scope": "the applied input, not a cell and not a feeling",
        }

    def write(self, handle):
        handle.write(json.dumps(self.record(), ensure_ascii=False) + "\n")
        return self.record()