"""One pain episode, end to end: stimulus, connectome, body, record.

This is the seam the dataset needs. Until now the four ingredients lived in four
probes: the forced network produced a raster, the body walked on its own gait, the
episode record knew how to hold all of it, and the nociception series knew which
cells an abdominal stimulus reaches. This module puts them in one function so that
an episode is a call, not a script.

Two deliberate limits, both measured elsewhere and both stated here so nobody reads
the output as more than it is:

  * the stimulus is applied by FORCING cells to fire. That is how the whole
    nociception series was measured (run_forced_network), because the field solve
    over the full population costs about twenty minutes per point. A forced burst is
    the connectome half of the experiment; the field half is joined in by the caller
    that owns one, through the electrode argument;
  * the body has a gait but no thorax muscle model and no wings, so an episode can
    report displacement and abdominal curl and cannot report flight or grooming.

Units: the twin works in centimetres, radians and seconds; the stimulus is given in
micrometres and nanoamperes so that it matches the field configuration.
"""

from __future__ import annotations

import json

import numpy as np

from .episode import Episode
from .loop import BehaviourLoop
from .twin import TwinBody

# A stimulus is a pulse, not a step: 2-3 ms is what the field configuration applies,
# and the connectome is driven on the same grid.
DEFAULT_ONSET_MS = 3
DEFAULT_DURATION_MS = 120


def _raster(result, ids):
    """Turn the network result into a millisecond -> neuron -> count mapping.

    run_forced_network reports POSITIONS in the graph, not body ids. Reading them as
    ids silently maps every spike onto the wrong cell, which is how an earlier build
    reported zero muscles reached for any stimulus; the conversion is done here once.
    """
    spikes = np.asarray(result["spike_neurons"])
    times = np.asarray(result["spike_times_ms"])
    raster = {}
    for position, when in zip(spikes.tolist(), times.tolist()):
        neuron = int(ids[int(position)])
        tick = int(round(float(when)))
        burst = raster.setdefault(tick, {})
        burst[neuron] = burst.get(neuron, 0) + 1
    return raster


def _activity(raster, duration_ms):
    """The per-millisecond spike counter, the channel the electrode trace cannot carry."""
    counts = np.zeros(int(duration_ms) + 1, dtype=np.int64)
    for tick, burst in raster.items():
        if 0 <= tick < len(counts):
            counts[tick] += sum(int(v) for v in burst.values())
    return counts


def _curl(body, joints):
    return float(sum(float(body.data.qpos[body.qpos_index[name]]) for name in joints))


def run_episode(graph, *, source_cells, current_na, site_um, seed=1,
                duration_ms=DEFAULT_DURATION_MS, onset_ms=DEFAULT_ONSET_MS,
                body=None, loop=None, reason="", electrode=None,
                allow_silent=False, escape_threshold=None):
    """Run one stimulus through the connectome and the body and return the record.

    The source_cells argument names the cells the stimulus drives. Which cells a
    stimulus at a given site reaches is the job of the field solve; this function
    takes that as given.
    """
    ids = np.asarray(graph.ids)
    # A zero-dose control is a real episode, so an absent stimulus is spelled None.
    # An empty list stays an error: it means the caller asked for cells and got none,
    # which is a field-solve failure and must not be recorded as silence.
    present = set(int(v) for v in ids)
    cells = [] if source_cells is None else sorted(int(c) for c in source_cells
                                                  if int(c) in present)
    # Two different silences. An absent stimulus is a control and is always allowed.
    # An empty set of cells that the caller meant to drive is a field-solve failure
    # and must not be written down as silence, unless the caller says the dose was
    # below threshold on purpose -- then it is a measured sub-threshold episode.
    if source_cells is not None and not cells and not allow_silent:
        raise ValueError("No source cell is present in the graph")
    silent = not cells

    if silent:
        raster = {}
        activity = np.zeros(int(duration_ms) + 1, dtype=np.int64)
        spikes = np.zeros(0, dtype=np.int64)
        times = np.zeros(0, dtype=float)
    else:
        from ..connectome.forced_network import run_forced_network

        result = run_forced_network(graph, seed=int(seed),
                                    duration_ms=int(duration_ms),
                                    forced_cell_ids=cells,
                                    events={cell: [int(onset_ms)] for cell in cells})
        raster = _raster(result, ids)
        activity = _activity(raster, duration_ms)
        spikes = result["spike_neurons"]
        times = result["spike_times_ms"]

    owner = body is None
    if body is None:
        body = TwinBody()
    if loop is not None:
        control = loop
    elif escape_threshold is None:
        control = BehaviourLoop(body)
    else:
        control = BehaviourLoop(body, escape_threshold=int(escape_threshold))
    # A reused body carries the previous episode in it -- a displaced root, a curled
    # abdomen, an escape already triggered.  Measured in the first corpus run: seed 3
    # at -2400 nA moved 13.9 mm while seed 1 at the same current moved 1.5 mm, which
    # was the previous episode still walking.  The reset is what makes an episode an
    # episode.
    reset = getattr(control, "reset", None)
    if reset is not None:
        reset()
    control.settle()

    joints = [name for name in body.qpos_index
              if name.startswith("abdomen") and "abduct" not in name]
    start = body.state()["position_cm"]
    curl0 = _curl(body, joints)
    heights = []
    for tick in range(1, int(duration_ms) + 1):
        control.advance(0.001, raster.get(tick))
        heights.append(float(body.data.qpos[2]))
    end = body.state()["position_cm"]
    curl1 = _curl(body, joints)

    # The raster is stored as body ids. run_forced_network reports positions in the
    # graph, so a record that stored them unchanged would name cells that do not exist
    # in any other view of the connectome; the record module says so and this is the one
    # place the conversion happens.
    neuron_ids = np.asarray([int(ids[int(p)]) for p in np.asarray(spikes).tolist()], dtype=np.int64)
    record = Episode(seed=seed, site_um=site_um, current_na=current_na,
                     source_cells=cells, duration_ms=duration_ms, reason=reason)
    record.record_network(spikes=spikes, spike_neurons=neuron_ids, spike_times_ms=times,
                          activity=activity, cell_ids=ids)
    record.record_body(start=start, end=end, curl_start=curl0, curl_end=curl1,
                       escape_latency_ms=control.escape_latency_ms,
                       peak_height_cm=max(heights) if heights else float(body.data.qpos[2]),
                       min_height_cm=min(heights) if heights else float(body.data.qpos[2]))
    if electrode is not None:
        record.record_electrode(**electrode)
    if owner:
        # The caller did not hand a body in, so this call owns it and its state must
        # not leak into the next episode.
        record.body["body_owned"] = True
    return record, control


def write_dataset(records, path):
    """Write episodes as one JSON object per line; returns the number written."""
    written = 0
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.record(), ensure_ascii=False) + "\n")
            written += 1
    return written
