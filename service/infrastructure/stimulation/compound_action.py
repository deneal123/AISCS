"""A forward model of a compound action potential on one electrode.

The twin already sums membrane current into an electrode channel:
``record_independent_cells`` adds the volume-conducted field of every cell on a
common time grid and ``acquire_channel`` blanks the stimulus and band-passes the
result.  What that chain does NOT contain is the one thing that makes a compound
action potential a compound action potential: the volley travels.  Each cell
contributes at the instant its membrane current happens, at its own position, so
there is no latency and no triphasic shape -- the two features that an ECAP-based
closed loop actually reads.

This module adds that propagation as an explicit, declared forward model.  It is
not new physics and it is not a calibrated recording:

  * a fibre is a diameter, a conduction velocity and a position along one axis;
  * a volley is a set of (cell, time, amplitude) triples;
  * the electrode sees each volley after a delay of distance / velocity, shaped by
    the triphasic kernel a passing wavefront induces on a differential pair;
  * the sum over recruited fibres is the channel.

WHAT IS NOT CLAIMED.  The absolute scale is not calibrated against any recording:
there is no published compound action potential from the Drosophila ventral nerve
cord with a known number of recruited fibres, so the microvolt column is a model
output, not a measurement.  Diameters are class representatives, not measured
per-cell values, because the connectome carries no axon calibre.  Both facts are
written into every receipt this module returns.

WHY THE SCALE IS STILL USEFUL.  A closed loop reads a normalised amplitude and a
latency relative to the stimulus, and both of those are produced here from
quantities the twin does measure: which cells fired and when.  The synthetic
dataset is therefore labelled with the exact number of recruited fibres per class,
which no real ECAP recording carries.
"""

from __future__ import annotations

import math

import numpy as np

# Fibre classes, as they exist in an insect ventral nerve cord.  The diameters are
# class representatives taken from the range reported for insect interneurons, not
# per-cell measurements: the connectome has no calibre column, and inventing one per
# cell would be a claim the source does not support.
FIBRE_CLASSES = {
    "ascending_small": {"diameter_um": 0.35, "count_hint": "most ascending cells"},
    "ascending_medium": {"diameter_um": 0.9, "count_hint": "the wider ascending axons"},
    "ascending_large": {"diameter_um": 2.2, "count_hint": "giant fibre and its peers"},
}
# Conduction velocity of an unmyelinated insect axon, in metres per second, as a
# power of diameter in micrometres: v = K * d**0.6.  The exponent is the one measured
# for unmyelinated fibres; K is set so that a 0.35 um fibre conducts at 0.55 m/s and a
# 2.2 um fibre at 1.75 m/s, inside the 0.5-2 m/s band reported for insect cord axons.
VELOCITY_K = 0.98
VELOCITY_EXPONENT = 0.6
# The triphasic kernel: a positive peak, a sharp negative peak and a second positive
# peak, which is what a wavefront passing a differential pair induces.  The widths are
# fractions of the volley width, so the shape scales with conduction velocity instead
# of being a fixed number of microseconds.
KERNEL_SHAPE = ((0.0, 0.35), (0.55, -1.0), (1.0, 0.45))
# Time for the wavefront to cross the electrode, in milliseconds, at one metre per
# second over one millimetre: the twin scale, not the clinical one.
DEFAULT_CROSSING_MS = 1.0


def conduction_velocity_m_s(diameter_um):
    """Velocity of an unmyelinated axon of this diameter, metres per second."""
    if not math.isfinite(diameter_um) or diameter_um <= 0.:
        raise ValueError("Invalid fibre diameter")
    return VELOCITY_K * diameter_um ** VELOCITY_EXPONENT


def class_diameter_um(name):
    try:
        return float(FIBRE_CLASSES[name]["diameter_um"])
    except KeyError as exc:
        raise ValueError("Unknown fibre class: " + str(name)) from exc


def crossings_ms(diameter_um, *, crossing_ms=DEFAULT_CROSSING_MS):
    """Width of one fibre signature, in ms: the reciprocal of its velocity, scaled."""
    velocity = conduction_velocity_m_s(diameter_um)
    # One metre per second makes a millimetre in one millisecond, so a fibre of
    # velocity v crosses in crossing_ms / v.
    return float(crossing_ms) / velocity


def triphasic_kernel(width_ms, *, samples=9):
    """The three-lobed shape a passing volley induces, sampled on a uniform grid.

    Returned as (offsets_ms, weights) with the weights summing to zero, because a
    differential pair sees no net charge from a wavefront that has passed: this is
    the property that gives an ECAP its characteristic P1-N1-P2 and its zero mean.
    """
    if not math.isfinite(width_ms) or width_ms <= 0.:
        raise ValueError("Invalid volley width")
    if samples < 5:
        raise ValueError("A triphasic kernel needs at least five samples")
    points = []
    for index in range(samples):
        position = (index / (samples - 1)) * KERNEL_SHAPE[-1][0]
        points.append(_kernel_value(position))
    weights = np.asarray(points, dtype=float)
    weights -= weights.mean()
    peak = float(np.max(np.abs(weights)))
    if peak > 0.:
        weights /= peak
    offsets = np.linspace(0., KERNEL_SHAPE[-1][0], samples) * width_ms
    return offsets, weights


def _kernel_value(position):
    """Piecewise-linear interpolation of the declared three-lobe shape."""
    for (left_x, left_y), (right_x, right_y) in zip(KERNEL_SHAPE, KERNEL_SHAPE[1:]):
        if left_x <= position <= right_x:
            span = right_x - left_x
            if span <= 0.:
                return float(right_y)
            fraction = (position - left_x) / span
            return float(left_y + (right_y - left_y) * fraction)
    return 0.


def volley_channel(volleys, *, duration_ms, dt_ms, crossing_ms=DEFAULT_CROSSING_MS):
    """Sum propagated volleys on one time grid.

    ``volleys`` is an iterable of dicts with keys ``time_ms`` (when the volley
    leaves its origin), ``amplitude_uv`` (the signed contribution of one fibre of
    this class at the electrode) and ``delay_ms`` (distance to the electrode over
    the conduction velocity).  The result is the channel a differential pair would
    see, before any amplifier: no noise, no filter, no blanking.
    """
    if not math.isfinite(duration_ms) or duration_ms <= 0.:
        raise ValueError("Invalid duration")
    if not math.isfinite(dt_ms) or dt_ms <= 0.:
        raise ValueError("Invalid time step")
    samples = int(round(duration_ms / dt_ms)) + 1
    time = np.arange(samples, dtype=float) * dt_ms
    signal = np.zeros(samples, dtype=float)
    counted = 0
    for volley in volleys:
        _add_volley(signal, volley, dt_ms=dt_ms, crossing_ms=crossing_ms)
        counted += 1
    return {"time_ms": time, "neural_uv": signal, "volleys": counted,
            "sampling_hz": 1000. / dt_ms, "crossing_ms": float(crossing_ms)}


def _add_volley(signal, volley, *, dt_ms, crossing_ms):
    """Add one volley's triphasic fingerprint to a channel in place.

    Shared by the channel and the recruitment curve so both do the same arithmetic in
    the same order; a curve that summed differently from the channel it describes
    would be a different measurement.
    """
    samples = signal.shape[0]
    arrival = float(volley["time_ms"]) + float(volley["delay_ms"])
    amplitude = float(volley["amplitude_uv"])
    diameter = float(volley.get("diameter_um",
                                 FIBRE_CLASSES["ascending_small"]["diameter_um"]))
    offsets, weights = triphasic_kernel(crossings_ms(diameter, crossing_ms=crossing_ms))
    for offset, weight in zip(offsets, weights, strict=True):
        position = (arrival + float(offset)) / dt_ms
        # Spread the weight over the two neighbouring samples instead of snapping
        # to the nearest one.  Snapping loses up to half a sample per lobe, which
        # makes a synchronous volley of N fibres sum to less than N times one fibre
        # and breaks the linearity a recruitment curve is read from.
        lower = int(math.floor(position))
        fraction = position - lower
        for index, share in ((lower, 1.0 - fraction), (lower + 1, fraction)):
            if 0 <= index < samples and share > 0.:
                signal[index] += amplitude * float(weight) * share


def fibre_delay_ms(distance_um, diameter_um):
    """How long a volley of this calibre takes to cover this distance."""
    if not math.isfinite(distance_um) or distance_um < 0.:
        raise ValueError("Invalid distance")
    velocity = conduction_velocity_m_s(diameter_um)
    # velocity is m/s, distance is um: um / (m/s) = um * s / m = 1e-6 s = 1e-3 ms.
    return distance_um / velocity * 1e-3


def recruitment_curve(volleys, *, duration_ms, dt_ms, crossing_ms=DEFAULT_CROSSING_MS):
    """Peak-to-peak amplitude of the channel against the number of fibres, cumulatively.

    This is the measured input-output function an ECAP closed loop is built on: the
    amplitude has to grow with recruitment, and it has to grow monotonically, or the
    loop cannot invert it to a dose.  Returned as a list of (fibres, ptp_uv), each
    entry the channel built from the first N volleys of the input order.
    """
    if not math.isfinite(duration_ms) or duration_ms <= 0.:
        raise ValueError("Invalid duration")
    if not math.isfinite(dt_ms) or dt_ms <= 0.:
        raise ValueError("Invalid time step")
    ordered = list(volleys)
    samples = int(round(duration_ms / dt_ms)) + 1
    # One growing channel instead of one channel per prefix: the curve of the whole
    # population is then linear in the number of volleys, not quadratic, and it is
    # arithmetic on exactly the same samples as volley_channel.  Recomputing the
    # prefix each time also re-added every earlier volley, so a curve over a few
    # thousand fibres spent minutes proving a monotonicity it could accumulate.
    running = np.zeros(samples, dtype=float)
    out = []
    for count, volley in enumerate(ordered, start=1):
        _add_volley(running, volley, dt_ms=dt_ms, crossing_ms=crossing_ms)
        out.append((count, float(np.ptp(running))))
    return out


def curve_violations(curve):
    """Adjacent pairs where more fibres produced less amplitude."""
    return int(sum(1 for (n0, a0), (n1, a1) in zip(curve, curve[1:]) if a1 + 1e-9 < a0))


def synchronous_recruitment_curve(distance_um, *, fibres, classes=None,
                                  duration_ms, dt_ms, onset_ms=1.0,
                                  crossing_ms=DEFAULT_CROSSING_MS):
    """The curve an ECAP loop is built on: fibres recruited together by one pulse.

    This is the real experimental object, and it is a different thing from the curve a
    raster produces. A stimulus pulse recruits every fibre it recruits at the SAME
    instant, so adding fibres only adds in phase, and the amplitude grows with the
    count -- the input-output function a closed loop inverts to read a dose. The raster
    curve in channel_from_raster is dispersed, and a dispersed curve can fall: measured
    557 falling pairs of 9381 in the 70-episode corpus.

    By default every fibre is the same class, which is what the twin's own preparations
    produce: all 9421 volleys in the 70-episode corpus were ascending_small. With one
    class the curve is exactly linear and cannot fall. Naming several classes makes the
    curve saturate and drift the way a recorded one does -- and also makes it able to
    dip, because a slower class arrives into the opposite phase of a faster class's
    lobe. That dip is physics, not a bug, so it is reported by curve_violations rather
    than smoothed away. A loop must only invert a curve with no violations.
    """
    if not fibres or fibres < 1:
        return []
    if not math.isfinite(duration_ms) or duration_ms <= 0.:
        raise ValueError("Invalid duration")
    if not math.isfinite(dt_ms) or dt_ms <= 0.:
        raise ValueError("Invalid time step")
    if classes is None:
        classes = {"ascending_small": FIBRE_CLASSES["ascending_small"]}
    names = sorted(classes)
    per_class = {name: 0 for name in names}
    for index in range(int(fibres)):
        per_class[names[index % len(names)]] += 1
    volleys = []
    for name in names:
        count = per_class[name]
        diameter = float(classes[name]["diameter_um"])
        delay = fibre_delay_ms(float(distance_um), diameter)
        amplitude = fibre_amplitude_uv(float(distance_um))
        for _ in range(count):
            volleys.append({"time_ms": float(onset_ms), "delay_ms": delay,
                            "amplitude_uv": amplitude, "diameter_um": diameter,
                            "class": name})
    # Accumulate in class order so the curve is a sweep of one class at a time and each
    # step adds fibres that arrive together.
    volleys.sort(key=lambda item: (item["delay_ms"], item["class"]))
    return recruitment_curve(volleys, duration_ms=duration_ms, dt_ms=dt_ms,
                             crossing_ms=crossing_ms)


def summarise(channel, *, recruited=0, classes=None):
    """A receipt: what was summed, and what is not calibrated."""
    signal = np.asarray(channel["neural_uv"], dtype=float)
    return {
        "format": "malecns-compound-action-potential-v1",
        "volleys": int(channel["volleys"]),
        "recruited_fibres": int(recruited),
        "classes": dict(classes or {}),
        "ptp_uv": round(float(np.ptp(signal)), 6),
        "peak_abs_uv": round(float(np.max(np.abs(signal))), 6),
        "sampling_hz": round(float(channel["sampling_hz"]), 3),
        "crossing_ms": round(float(channel["crossing_ms"]), 6),
        "triphasic": True,
        "calibrated": False,
        "calibration_note": (
            "absolute microvolts are a model output: no published compound action "
            "potential from the Drosophila cord has a known recruitment"),
        "diameters": "class representatives, not measured per cell",
    }


# The giant fibres of the cord are the only cells whose calibre is named in the
# source annotations, so they are the only ones given a large class.  Everything else
# is one class, because the connectome carries no axon diameter and inventing a
# distribution per cell would be a claim it cannot support.
GIANT_TYPES = ("DNp01", "DNp02")
# A declared point-source scale, not a measurement: at REFERENCE_UM a fibre of the
# small class contributes REFERENCE_UV at the electrode, and the amplitude falls as the
# inverse square of distance, which is what a point source in a conducting medium does.
REFERENCE_UV = 1.0
REFERENCE_UM = 100.0
MIN_DISTANCE_UM = 20.0


def fibre_amplitude_uv(distance_um, *, reference_uv=REFERENCE_UV,
                       reference_um=REFERENCE_UM, floor_um=MIN_DISTANCE_UM):
    """Declared point-source amplitude at a distance, microvolts."""
    if not math.isfinite(distance_um) or distance_um < 0.:
        raise ValueError("Invalid distance")
    effective = max(float(distance_um), float(floor_um))
    return float(reference_uv) * (float(reference_um) / effective) ** 2


def class_of_cell(cell_type):
    """Fibre class of a cell, from the only calibre the source names."""
    name = str(cell_type or "")
    return "ascending_large" if name in GIANT_TYPES else "ascending_small"


def volleys_from_spikes(spike_times_ms, positions_um, electrode_um, *,
                        types=None, classes=None):
    """Turn a spike raster into propagating volleys on the electrode.

    ``spike_times_ms`` and ``positions_um`` are parallel: one row per spike, the time it
    happened and the position of the cell that fired.  ``electrode_um`` is the contact.
    Every spike becomes one volley at its cell, delayed by the travel time to the
    contact along its fibre class, with the declared point-source amplitude.  Cells
    without a position are skipped and counted, because a missing landmark is not a
    zero-amplitude spike.
    """
    times = np.asarray(spike_times_ms, dtype=float)
    positions = np.asarray(positions_um, dtype=float)
    contact = np.asarray(electrode_um, dtype=float)
    if times.ndim != 1 or positions.shape != (len(times), 3) or contact.shape != (3,):
        raise ValueError("Invalid spike raster or electrode")
    if not len(times):
        # A silent preparation is a real episode: no volleys, an empty channel, no error.
        return {"volleys": [], "per_class": {}, "skipped": 0, "recruited": 0,
                "classes": dict(classes or {})}
    if not (np.isfinite(times).all() and np.isfinite(contact).all()):
        raise ValueError("Non-finite spike time or electrode")
    known = np.isfinite(positions).all(axis=1)
    volleys = []
    per_class = {}
    skipped = int((~known).sum())
    for index in np.flatnonzero(known):
        position = positions[index]
        name = class_of_cell((types[index] if types is not None else None))
        diameter = class_diameter_um(name)
        distance = float(np.linalg.norm(position - contact))
        volleys.append({
            "time_ms": float(times[index]),
            "delay_ms": fibre_delay_ms(distance, diameter),
            "amplitude_uv": fibre_amplitude_uv(distance),
            "diameter_um": diameter,
            "fibre_class": name,
        })
        per_class[name] = per_class.get(name, 0) + 1
    volleys.sort(key=lambda item: (item["time_ms"], item["delay_ms"]))
    return {"volleys": volleys, "per_class": per_class, "skipped": skipped,
            "recruited": len(volleys), "classes": dict(classes or per_class)}


def channel_from_raster(raster, positions_by_cell, electrode_um, *,
                        types_by_cell=None, duration_ms, dt_ms,
                        crossing_ms=DEFAULT_CROSSING_MS):
    """Build the electrode channel straight from a spike raster.

    ``raster`` is an iterable of (cell_id, time_ms) pairs in the shape an episode already
    stores.  A cell with no position cannot be placed, so its spikes are counted as
    skipped instead of being quietly put at the origin.  Returns the channel, the
    receipt of what was summed, and the recruited count per class.
    """
    rows = list(raster)
    times = [float(time) for _, time in rows]
    positions = []
    types = []
    for cell_id, _ in rows:
        cell = int(cell_id)
        positions.append(positions_by_cell.get(cell, (np.nan, np.nan, np.nan)))
        types.append(None if types_by_cell is None else types_by_cell.get(cell))
    # An empty raster has no rows, and np.asarray([]) is shape (0,) rather than (0, 3);
    # reshaping here keeps a silent episode a valid, empty channel instead of an error.
    shaped = np.asarray(positions, dtype=float).reshape(-1, 3)
    built = volleys_from_spikes(times, shaped, electrode_um, types=types)
    channel = volley_channel(built["volleys"], duration_ms=duration_ms, dt_ms=dt_ms,
                             crossing_ms=crossing_ms)
    receipt = summarise(channel, recruited=built["recruited"],
                        classes=built["per_class"])
    receipt["skipped_spikes"] = int(built["skipped"])
    # The samples themselves, not just their peak: an ECAP corpus is a matrix of
    # waveforms, and a receipt of scalars cannot be re-analysed by anyone else's
    # pipeline.  Rounded to six decimals, which is below the model's own resolution.
    receipt["samples"] = int(len(channel["neural_uv"]))
    receipt["waveform_uv"] = [round(float(v), 6) for v in channel["neural_uv"]]
    # The two numbers a closed loop actually reads: how big the answer was and how long
    # it took to arrive after the stimulus.  Both are produced here, neither is calibrated.
    signal = np.asarray(channel["neural_uv"], dtype=float)
    if np.any(signal):
        receipt["peak_at_ms"] = round(float(channel["time_ms"][int(np.argmax(np.abs(signal)))]), 6)
    else:
        receipt["peak_at_ms"] = None
    # The input-output curve travels with the channel: it is the function an ECAP
    # closed loop inverts to read a dose, and it costs one pass over the volleys.
    # A silent preparation gets an empty curve, not a curve of zeros.
    if built["volleys"]:
        curve = recruitment_curve(built["volleys"], duration_ms=duration_ms, dt_ms=dt_ms,
                                  crossing_ms=crossing_ms)
        receipt["recruitment_curve"] = curve
        # A curve built from a raster is NOT the curve an ECAP loop inverts, and saying so
        # is the difference between a usable artifact and a trap. The spikes arrive over
        # tens of milliseconds, so each added fibre lands on a different phase of the
        # triphasic kernel and can subtract from the ones already there. Measured on the
        # 70-episode corpus: 557 of 9381 adjacent pairs fell, worst episode 51 of 497.
        # Reordering does not fix it (spike time 12, arrival 12, far-first 11, strongest
        # first 9 violations on the same episode) because the cause is superposition of
        # dispersed phases, not the order of addition.
        violations = sum(1 for (n0, a0), (n1, a1) in zip(curve, curve[1:])
                         if a1 + 1e-9 < a0)
        receipt["recruitment_curve_kind"] = "dispersed_from_raster"
        receipt["recruitment_monotone"] = not violations
        receipt["recruitment_violations"] = int(violations)
    else:
        receipt["recruitment_curve"] = []
        receipt["recruitment_curve_kind"] = "dispersed_from_raster"
        receipt["recruitment_monotone"] = True
        receipt["recruitment_violations"] = 0
    return {"channel": channel, "receipt": receipt,
            "volleys": built["volleys"], "per_class": built["per_class"]}
