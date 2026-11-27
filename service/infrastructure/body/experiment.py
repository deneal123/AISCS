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
  * the body's wings are driven by a flight programme rather than by the thorax's
    stretch-activated muscle, so what an episode reports for flight is the beat the
    wing motor neurons commanded and the lift that beat produces, not a spike-by-spike
    reconstruction of a 200 Hz oscillation (see flight.py for why that cannot be
    reconstructed at a 1 ms control grid).

Units: the twin works in centimetres, radians and seconds; the stimulus is given in
micrometres and nanoamperes so that it matches the field configuration.
"""

from __future__ import annotations

import json
import math

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


def _soma_positions_um(graph):
    """Soma landmarks in micrometres, keyed by body id.

    The connectome stores voxel corners of the soma (or, when the soma is not traced,
    the to-soma landmark) in 8 nm voxels; 0.008 turns them into micrometres. A cell
    with neither landmark is left out rather than placed at the origin, because an
    origin is inside the first thoracic neuromere and would be a false position.
    """
    info = graph.annotations
    positions = {}
    for index, cell in enumerate(np.asarray(graph.ids).tolist()):
        soma = info["somaLocation"][index]
        root = info["tosomaLocation"][index]
        point = soma if soma is not None else root
        if point is None:
            continue
        positions[int(cell)] = tuple(float(v) * 0.008 for v in point)
    return positions

def _activity(raster, duration_ms):
    """The per-millisecond spike counter, the channel the electrode trace cannot carry."""
    counts = np.zeros(int(duration_ms) + 1, dtype=np.int64)
    for tick, burst in raster.items():
        if 0 <= tick < len(counts):
            counts[tick] += sum(int(v) for v in burst.values())
    return counts


def _curl(body, joints):
    return float(sum(float(body.data.qpos[body.qpos_index[name]]) for name in joints))


def _heading(body):
    """Heading about the vertical axis, radian, from the free joint's quaternion.

    A displacement alone cannot tell an escape to the left from one to the right: both
    move the animal the same distance.  The heading is what carries the side.
    """
    w, x, y, z = [float(value) for value in body.data.qpos[3:7]]
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _turn_deg(start_rad, end_rad):
    """Signed heading change in degrees, wrapped to (-180, 180]."""
    delta = math.degrees(float(end_rad) - float(start_rad))
    while delta > 180.0:
        delta -= 360.0
    while delta <= -180.0:
        delta += 360.0
    return delta


def run_episode(graph, *, source_cells, current_na, site_um, seed=1,
                duration_ms=DEFAULT_DURATION_MS, onset_ms=DEFAULT_ONSET_MS,
                body=None, loop=None, reason="", electrode=None,
                allow_silent=False, escape_threshold=None, onsets_ms=None,
                flight_recruitment=None, electrode_um=None, fibre_classes=True):
    """Run one stimulus through the connectome and the body and return the record.

    The source_cells argument names the cells the stimulus drives. Which cells a
    stimulus at a given site reaches is the job of the field solve; this function
    takes that as given.

    When electrode_um names a contact, the episode also carries a compound action
    potential: every spike is turned into a volley that travels to the contact at the
    conduction velocity of its fibre class, and the sum of those volleys is recorded
    as an uncalibrated forward model. The stimuli used here fire the whole graph -- a
    forced-network preparation has no way to fire only the ascending layer -- so the
    channel is reported as it is built rather than as a cord volley.
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

        # A stimulus may be a train, not a single pulse. The connectome takes a list
        # of times per cell, so repetition is expressed here rather than by running
        # the network several times: the later pulses then land on a network that the
        # earlier ones have already changed, which is the whole point of asking
        # whether a sub-threshold dose sums.
        times_ms = [int(v) for v in onsets_ms] if onsets_ms else [int(onset_ms)]
        result = run_forced_network(graph, seed=int(seed),
                                    duration_ms=int(duration_ms),
                                    forced_cell_ids=cells,
                                    events={cell: list(times_ms) for cell in cells})
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
    # The caller may command a beat outright.  That is how a flight episode is made:
    # the connectome's wing neurons decide in the animal, and a forced-network
    # preparation cannot produce a 200 Hz drive from a 1 ms raster, so the command is
    # declared rather than inferred when it is not inferred.
    beat = None
    if flight_recruitment is not None:
        start_flight = getattr(control, "start_flight", None)
        if start_flight is not None:
            beat = start_flight(float(flight_recruitment))
    start = body.state()["position_cm"]
    curl0 = _curl(body, joints)
    heading0 = _heading(body)
    heights = []
    for tick in range(1, int(duration_ms) + 1):
        control.advance(0.001, raster.get(tick))
        heights.append(float(body.data.qpos[2]))
    end = body.state()["position_cm"]
    curl1 = _curl(body, joints)
    heading1 = _heading(body)

    # The raster is stored as body ids. run_forced_network reports positions in the
    # graph, so a record that stored them unchanged would name cells that do not exist
    # in any other view of the connectome; the record module says so and this is the one
    # place the conversion happens.
    neuron_ids = np.asarray([int(ids[int(p)]) for p in np.asarray(spikes).tolist()], dtype=np.int64)
    record = Episode(seed=seed, site_um=site_um, current_na=current_na,
                     source_cells=cells, duration_ms=duration_ms, reason=reason)
    record.record_network(spikes=spikes, spike_neurons=neuron_ids, spike_times_ms=times,
                          activity=activity, cell_ids=ids)
    programme = getattr(control, "flight", None)
    airborne = (float(max(heights)) - float(heights[0])) if len(heights) > 1 else 0.0
    record.record_body(start=start, end=end, curl_start=curl0, curl_end=curl1,
                       heading_start_rad=heading0,
                       turn_deg=_turn_deg(heading0, heading1),
                       escape_latency_ms=control.escape_latency_ms,
                       peak_height_cm=max(heights) if heights else float(body.data.qpos[2]),
                       min_height_cm=min(heights) if heights else float(body.data.qpos[2]),
                       motor_spikes=getattr(control, "motor_spikes", 0),
                       mapped_first_tick_ms=getattr(control, "mapped_first_tick_ms", None),
                       flight=dict(
                           latency_ms=getattr(control, "flight_latency_ms", None),
                           wing_spikes=getattr(control, "wing_spikes", 0),
                           lift_to_weight=(programme.force()["lift_to_weight"]
                                           if programme is not None else 0.0),
                           airborne_cm=airborne,
                           beating=bool(programme is not None and programme.amplitude_rad)))
    if electrode is not None:
        record.record_electrode(**electrode)
    if electrode_um is not None:
        from ..stimulation.compound_action import channel_from_raster

        built = channel_from_raster(
            [(int(cell), float(time)) for cell, time in zip(neuron_ids.tolist(),
                                                            times.tolist(),
                                                            strict=True)],
            _soma_positions_um(graph), electrode_um,
            duration_ms=float(duration_ms), dt_ms=0.05)
        receipt = dict(built["receipt"])
        # Say what this channel is not. A forced-network preparation fires every cell it
        # is told to fire, and here it is told to fire the whole graph, so the volley is
        # the whole graph arriving, not the ascending layer of a real cord.
        receipt["preparation"] = "whole_graph_forced"
        receipt["fibre_classes"] = bool(fibre_classes)
        record.record_compound_action(receipt)
    if owner:
        # The caller did not hand a body in, so this call owns it and its state must
        # not leak into the next episode.
        record.body["body_owned"] = True
    return record, control



def run_closed_episode(graph, *, source_cells, current_na, site_um, seed=1,
                       duration_ms=DEFAULT_DURATION_MS, onset_ms=DEFAULT_ONSET_MS,
                       body=None, reason="", electrode=None,
                       sense_cells=None, onsets_ms=None,
                       flight_recruitment=None, escape_threshold=None):
    """One episode with the loop closed: the body is heard while the stimulus runs.

    run_episode hands the body a raster that was computed before the body moved, so
    the network cannot react to the pose it produced. Here the graph advances one
    millisecond at a time against the body, and the joint angles the body reached
    are encoded as spikes on the proprioceptive cells and delivered back into the
    same queue the stimulus uses (see coupled.py and proprioception.py).

    ``sense_cells`` is a mapping of sensory class to the body ids that carry it, in
    the shape Proprioception takes. It is required: an episode that claims to be
    closed loop and has no sensors is an open episode with a longer name.
    """
    if not sense_cells:
        raise ValueError("A closed episode needs the sensory cells that close it")
    from .coupled import run_closed_loop
    from .proprioception import Proprioception

    ids = np.asarray(graph.ids)
    present = {int(v) for v in ids}
    cells = [] if source_cells is None else sorted(int(c) for c in source_cells
                                                  if int(c) in present)
    if source_cells is not None and not cells:
        raise ValueError("No source cell is present in the graph")
    times_ms = [int(v) for v in onsets_ms] if onsets_ms else [int(onset_ms)]
    # Only the stimulus cells are pushed, at the onsets the caller asked for. An earlier
    # version replayed the whole forced raster and thereby forced the network's own
    # answer as well, which made the closed episode a recording of the open one with
    # body spikes pasted on top.
    forced = {tick: list(cells) for tick in times_ms} if cells else {}

    owner = body is None
    if body is None:
        body = TwinBody()
    if escape_threshold is None:
        control = BehaviourLoop(body)
    else:
        control = BehaviourLoop(body, escape_threshold=int(escape_threshold))
    reset = getattr(control, "reset", None)
    if reset is not None:
        reset()
    control.settle()
    sense = Proprioception(body, sense_cells)

    joints = [name for name in body.qpos_index
              if name.startswith("abdomen") and "abduct" not in name]
    if flight_recruitment is not None:
        start_flight = getattr(control, "start_flight", None)
        if start_flight is not None:
            start_flight(float(flight_recruitment))
    start = body.state()["position_cm"]
    curl0 = _curl(body, joints)
    heading0 = _heading(body)
    heights = []

    def watch(tick, spikes):
        heights.append(float(body.data.qpos[2]))

    result, control = run_closed_loop(graph, controller=control,
                                      proprioception=sense,
                                      duration_ms=int(duration_ms),
                                      forced=forced, source_cells=cells,
                                      seed=int(seed), on_tick=watch)
    end = body.state()["position_cm"]
    curl1 = _curl(body, joints)
    heading1 = _heading(body)

    spikes = np.asarray(result["spike_neurons"])
    stamps = np.asarray(result["spike_times_ms"])
    neuron_ids = np.asarray([int(ids[int(p)]) for p in spikes.tolist()], dtype=np.int64)
    raster = {}
    for position, when in zip(spikes.tolist(), stamps.tolist()):
        burst = raster.setdefault(int(round(float(when))), {})
        neuron = int(ids[int(position)])
        burst[neuron] = burst.get(neuron, 0) + 1
    activity = _activity(raster, duration_ms)

    record = Episode(seed=seed, site_um=site_um, current_na=current_na,
                     source_cells=cells, duration_ms=duration_ms, reason=reason)
    record.record_network(spikes=spikes, spike_neurons=neuron_ids,
                          spike_times_ms=stamps, activity=activity, cell_ids=ids)
    programme = getattr(control, "flight", None)
    airborne = (float(max(heights)) - float(heights[0])) if len(heights) > 1 else 0.0
    record.record_body(start=start, end=end, curl_start=curl0, curl_end=curl1,
                       heading_start_rad=heading0,
                       turn_deg=_turn_deg(heading0, heading1),
                       escape_latency_ms=control.escape_latency_ms,
                       peak_height_cm=max(heights) if heights else float(body.data.qpos[2]),
                       min_height_cm=min(heights) if heights else float(body.data.qpos[2]),
                       motor_spikes=getattr(control, "motor_spikes", 0),
                       mapped_first_tick_ms=getattr(control, "mapped_first_tick_ms", None),
                       flight=dict(
                           latency_ms=getattr(control, "flight_latency_ms", None),
                           wing_spikes=getattr(control, "wing_spikes", 0),
                           lift_to_weight=(programme.force()["lift_to_weight"]
                                           if programme is not None else 0.0),
                           airborne_cm=airborne,
                           beating=bool(programme is not None and programme.amplitude_rad)))
    record.record_loop(sense.record(), body_events=int(result.get("body_events", 0)))
    if electrode is not None:
        record.record_electrode(**electrode)
    if owner:
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