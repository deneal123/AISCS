"""Pack an episode corpus into the shape an ECAP pipeline already reads.

A real compound-action-potential corpus is, in practice, three things: a matrix of
waveforms aligned on the stimulus, one row of protocol parameters per waveform, and a
recruitment curve somebody has already inverted. Almost every published ECAP study
publishes those three in some private arrangement, which is why corpora are rarely
reusable across labs. This module writes them in the arrangement that needs no
translation:

  waveforms.npz   time_ms (shared grid), signals (episodes x samples), episode ids
  protocol.csv    one row per episode: site, current, pulse width, duration, seed
  channels.csv    the derived quantities an ECAP pipeline computes: ptp, N1/P1,
                  recruited fibres, latency, and the behaviour that followed
  recruitment.csv the cumulative amplitude-against-fibres curve of every episode
  card.json       field-by-field description, including what is NOT calibrated

The one column here that no real corpus can have is ``recruited_fibres``. A real
ECAP is used to ESTIMATE how many fibres fired, and never reports it; the twin knows
the count exactly because it built the volley. That asymmetry is the point of the
export, and the card says so rather than letting a reader assume the column was
measured.
"""

from __future__ import annotations

import csv
import json

import numpy as np

FORMAT = "malecns-ecap-compatible-v1"
DT_MS = 0.05


def _signal(record):
    """The waveform of one episode, or None when the episode has no channel.

    A receipt that carries only its peak is treated as absent rather than as a flat
    line: the peak was computed from samples nobody kept, and re-inventing them here
    would be fabricating the only part of the corpus a reader can re-analyse.
    """
    block = record.get("compound_action") or {}
    samples = block.get("waveform_uv")
    if not samples:
        return None
    return np.asarray(samples, dtype=float)


def waveforms(records, dt_ms=DT_MS):
    """Stack the channels on one time grid, padding a short one with zeros.

    A channel that is missing entirely is left out and counted, not padded: a row of
    zeros would read as a measured flat line, which is the one thing a silent
    preparation is not.
    """
    rows = []
    kept = []
    for record in records:
        signal = _signal(record)
        if signal is None or not len(signal):
            continue
        rows.append(signal)
        kept.append(record)
    if not rows:
        return {"time_ms": np.zeros(0), "signals": np.zeros((0, 0)), "records": []}
    width = max(len(row) for row in rows)
    stacked = np.zeros((len(rows), width))
    for index, row in enumerate(rows):
        stacked[index, :len(row)] = row
    return {"time_ms": np.arange(width) * float(dt_ms), "signals": stacked,
            "records": kept}


def n1_p1(signal, time_ms, *, search_ms=(0.5, 40.0)):
    """The two landmarks an ECAP pipeline reads: first trough and the peak after it.

    Returned with the times, because a latency without its timebase is not a latency.
    A flat channel returns None for both rather than a zero that would look measured.
    """
    signal = np.asarray(signal, dtype=float)
    time_ms = np.asarray(time_ms, dtype=float)
    if not len(signal) or not np.any(signal):
        return {"n1_uv": None, "n1_ms": None, "p1_uv": None, "p1_ms": None}
    window = (time_ms >= search_ms[0]) & (time_ms <= search_ms[1])
    if not window.any():
        return {"n1_uv": None, "n1_ms": None, "p1_uv": None, "p1_ms": None}
    index = np.flatnonzero(window)
    local = signal[index]
    trough = int(index[int(np.argmin(local))])
    after = index[index > trough]
    if not len(after):
        return {"n1_uv": round(float(signal[trough]), 6),
                "n1_ms": round(float(time_ms[trough]), 6),
                "p1_uv": None, "p1_ms": None}
    crest = int(after[int(np.argmax(signal[after]))])
    return {"n1_uv": round(float(signal[trough]), 6),
            "n1_ms": round(float(time_ms[trough]), 6),
            "p1_uv": round(float(signal[crest]), 6),
            "p1_ms": round(float(time_ms[crest]), 6)}


def recruitment_csv(rows):
    """Cumulative amplitude against fibres, one curve per episode, sorted by fibres."""
    out = []
    for name, curve in rows:
        for fibres, amplitude in sorted(curve):
            out.append({"episode": name, "recruited_fibres": int(fibres),
                        "ptp_uv": round(float(amplitude), 6)})
    return out


def export(records, directory, *, dt_ms=DT_MS, card_extra=None):
    """Write the five files and return the card that describes them."""
    from pathlib import Path

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bundle = waveforms(records, dt_ms=dt_ms)
    kept = bundle["records"]
    absent = len(records) - len(kept)

    ids = np.asarray([f"ep{index:05d}" for index in range(len(kept))])
    np.savez_compressed(directory / "waveforms.npz",
                        time_ms=bundle["time_ms"], signals=bundle["signals"],
                        episode_id=ids)

    protocol_rows = []
    channel_rows = []
    curves = []
    for index, record in enumerate(kept):
        name = str(ids[index])
        block = record.get("compound_action") or {}
        body = record.get("body") or {}
        protocol_rows.append({
            "episode": name,
            "site_um": " ".join(f"{float(v):.3f}" for v in (record.get("site_um") or ()))
            ,
            "current_na": float(record.get("current_na") or 0.0),
            "pulse_width_ms": 1.0,
            "duration_ms": int(record.get("duration_ms") or 0),
            "dt_ms": float(dt_ms),
            "seed": int(record.get("seed") or 0),
        })
        landmarks = n1_p1(bundle["signals"][index], bundle["time_ms"])
        channel_rows.append({
            "episode": name,
            "ptp_uv": float(block.get("ptp_uv") or 0.0),
            "peak_at_ms": ("" if block.get("peak_at_ms") is None
                           else float(block["peak_at_ms"])),
            "n1_uv": "" if landmarks["n1_uv"] is None else landmarks["n1_uv"],
            "n1_ms": "" if landmarks["n1_ms"] is None else landmarks["n1_ms"],
            "p1_uv": "" if landmarks["p1_uv"] is None else landmarks["p1_uv"],
            "p1_ms": "" if landmarks["p1_ms"] is None else landmarks["p1_ms"],
            "recruited_fibres": int(block.get("recruited_fibres") or 0),
            "classes": " ".join(sorted((block.get("classes") or {}).keys())),
            "skipped_spikes": int(block.get("skipped_spikes") or 0),
            "escaped": bool(body.get("escape_latency_ms") is not None),
            "escape_latency_ms": ("" if body.get("escape_latency_ms") is None
                                   else float(body["escape_latency_ms"])),
            "curl_rad": float(body.get("curl_change_rad") or 0.0),
            "displacement_mm": float(body.get("displacement_mm") or 0.0),
            "calibrated": False,
        })
        curve = block.get("recruitment_curve")
        if curve:
            curves.append((name, [(int(n), float(a)) for n, a in curve]))

    _write_csv(directory / "protocol.csv", protocol_rows)
    _write_csv(directory / "channels.csv", channel_rows)
    _write_csv(directory / "recruitment.csv", recruitment_csv(curves))

    amplitudes = [row["ptp_uv"] for row in channel_rows]
    card = {
        "format": FORMAT,
        "episodes": len(kept),
        "episodes_without_channel": int(absent),
        "files": ["waveforms.npz", "protocol.csv", "channels.csv",
                  "recruitment.csv", "card.json"],
        "waveform_samples": int(bundle["signals"].shape[1]),
        "sampling_hz": round(1000.0 / float(dt_ms), 3),
        "calibrated": False,
        "exact_columns": ["recruited_fibres", "classes", "escaped",
                          "escape_latency_ms", "curl_rad", "displacement_mm"],
        "modelled_columns": ["ptp_uv", "n1_uv", "p1_uv", "peak_at_ms"],
        "why": ("recruited_fibres is exact because the twin built the volley; the "
                "microvolt scale is a declared point-source model, so amplitudes are "
                "comparable within this corpus and not to a recorded ECAP"),
        "compatible_with": ["waveform matrix corpora", "recruitment-curve corpora",
                            "stimulus-response tables"],
        "paired_with_behaviour": True,
        "ptp_range_uv": ([round(min(amplitudes), 6), round(max(amplitudes), 6)]
                         if amplitudes else None),
    }
    if card_extra:
        card.update(card_extra)
    (directory / "card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return card


def _write_csv(path, rows):
    path = str(path);
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("");
        return 0
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
