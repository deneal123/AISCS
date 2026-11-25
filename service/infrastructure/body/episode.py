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
                    peak_height_cm, min_height_cm):
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
        }
        return self.body

    def record_electrode(self, *, ptp_uv, tail_abs_max_uv, samples, source):
        """The field recording is joined in by whoever owns a field solve."""
        self.electrode = {
            "ptp_uv": round(float(ptp_uv), 4),
            "tail_abs_max_uv": round(float(tail_abs_max_uv), 6),
            "samples": int(samples),
            "source": str(source),
        }
        return self.electrode

    def labels(self):
        """What may be claimed from this episode, and nothing more."""
        labels = []
        if self.network.get("spike_count", 0) > 0:
            labels.append(LABEL_NOXIOUS_INPUT)
        if self.body.get("escape_latency_ms") is None:
            labels.append(LABEL_NO_ESCAPE)
        else:
            labels.append(LABEL_ESCAPE)
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
            "labels": self.labels(),
            # Stated once per record so a reader cannot mistake the label for a
            # statement about a cell.
            "label_scope": "the applied input, not a cell and not a feeling",
        }

    def write(self, handle):
        handle.write(json.dumps(self.record(), ensure_ascii=False) + "\n")
        return self.record()
