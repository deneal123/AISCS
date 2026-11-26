"""The dataset schema, defined only from what the twin was measured to show.

Six measurements decided this schema (report 38): dose is amplitude and does not
sum over pulses; the escape threshold sits at 3.4-3.5 uA; latency marks presence and
not strength; modality is invisible in the body response; the escape signature is
the abdominal curl, not the distance walked; and motor spikes must be counted
through the neuron-to-muscle map or they are wrong by two orders of magnitude.

What follows from those six is a hard rule: a label may only state something the
twin was measured to produce. The applied stimulus is a protocol fact, the escape
is a body measurement, and neither is a statement about a feeling. There is no
"pain" field and no per-cell "nociceptor" field, because neither was measured and
neither can be defended.
"""

from __future__ import annotations

import json
from collections import Counter

FORMAT = "malecns-twin-noxious-dataset-v1"

# The escape is called when the body both curls and the programme fired. The curl
# threshold is a twentieth of a radian: measured episodes sit at -0.16 to -0.19 rad
# when escaping and -0.013 to -0.016 when walking, so anything between -0.03 and
# -0.10 separates them and the exact cut does not matter (report 38, section 5).
ESCAPE_CURL_RAD = -0.05
# A noxious input is the applied current above the measured escape threshold. The
# protocol decides this, not the network: the threshold was measured at 3.4-3.5 uA
# and the behavioural interval in the earlier series was 3.0-3.6 uA, so the label
# uses the top of that interval and says so.
NOXIOUS_CURRENT_NA = -3600.0


def escape_signature(record):
    """The two measured marks of an escape, read from the body block."""
    body = record.get("body") or {}
    curl = body.get("curl_change_rad")
    latency = body.get("escape_latency_ms")
    curled = curl is not None and float(curl) <= ESCAPE_CURL_RAD
    fired = latency is not None
    return {"curl_rad": curl, "latency_ms": latency,
            "curled": bool(curled), "programme_fired": bool(fired),
            "escaped": bool(curled and fired)}


def label(record):
    """Add the dataset labels. Every one states what was applied or measured."""
    network = record.get("network") or {}
    body = record.get("body") or {}
    signature = escape_signature(record)
    current = record.get("current_na")
    recruited = int(record.get("source_cell_count") or 0)
    noxious = current is not None and float(current) <= NOXIOUS_CURRENT_NA
    return {
        "format": FORMAT,
        # Protocol facts. These are true by construction and do not depend on the
        # network at all, which is why the network can never validate them.
        "applied_current_na": current,
        "site_um": record.get("site_um"),
        "recruited_afferents": recruited,
        "noxious_input": bool(noxious) if current else False,
        # Network measurements.
        "spike_count": int(network.get("spike_count") or 0),
        "active_cells": int(network.get("cell_count") or 0),
        # Body measurements, and the two that carry the escape.
        "motor_spikes": int(body.get("motor_spikes") or 0),
        "curl_rad": signature["curl_rad"],
        "escape_latency_ms": signature["latency_ms"],
        "escaped": signature["escaped"],
        "displacement_mm": body.get("displacement_mm"),
        "label_scope": "the applied input and the measured body response, not a feeling",
    }


def site_key(record):
    site = record.get("site_um") or [0.0, 0.0, 0.0]
    return ",".join(f"{float(v):.1f}" for v in site)


def split_by_site(records):
    """Split by stimulus site, because episodes at one site are not independent.

    Splitting by episode would let one site appear on both sides and inflate every
    score: the site decides the recruited set, and the recruited set decides the
    outcome almost completely (report 38, sections 2 and 4).
    """
    sites = sorted({site_key(r) for r in records})
    train = [r for r in records if site_key(r) != sites[-1]]
    test = [r for r in records if site_key(r) == sites[-1]]
    return {"train": train, "test": test,
            "held_out_site": sites[-1] if sites else None}


def roc_auc(scores, labels):
    """Rank AUC with tied scores averaged, so a threshold baseline is not rewarded."""
    pairs = sorted(zip(scores, labels))
    positives = sum(1 for _, flag in pairs if flag)
    negatives = len(pairs) - positives
    if not positives or not negatives:
        return None
    rank_sum = 0.0
    index = 0
    while index < len(pairs):
        end = index
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(1 for _, flag in pairs[index:end] if flag)
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def baseline_escape(records):
    """How well the escape is predicted by the dose alone, with no network at all."""
    records = [r for r in records if r.get("current_na") is not None]
    if not records:
        return {}
    outcome = [escape_signature(r)["escaped"] for r in records]
    dose = [float(r.get("current_na") or 0.0) for r in records]
    recruited = [int(r.get("source_cell_count") or 0) for r in records]
    spikes = [int((r.get("network") or {}).get("spike_count") or 0) for r in records]
    return {"episodes": len(records),
            "escapes": int(sum(outcome)),
            "auc_by_current": roc_auc([-v for v in dose], outcome),
            "auc_by_recruited": roc_auc(recruited, outcome),
            "auc_by_spikes": roc_auc(spikes, outcome)}


def summarize(records):
    counts = Counter()
    curls = []
    latencies = []
    sites = Counter()
    for record in records:
        signature = escape_signature(record)
        counts["episodes"] += 1
        counts["escaped"] += int(signature["escaped"])
        counts["noxious_input"] += int(label(record)["noxious_input"])
        if signature["curl_rad"] is not None:
            curls.append(float(signature["curl_rad"]))
        if signature["latency_ms"] is not None:
            latencies.append(float(signature["latency_ms"]))
        sites[site_key(record)] += 1
    curls.sort()
    latencies.sort()
    return {"counts": dict(counts), "sites": dict(sites),
            "curl_range": [curls[0], curls[-1]] if curls else None,
            "latency_range": [latencies[0], latencies[-1]] if latencies else None}


def write(records, path):
    """One JSON object per line, labels included; returns the number written."""
    written = 0
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            merged = dict(record)
            merged["dataset"] = label(record)
            handle.write(json.dumps(merged, ensure_ascii=False) + "\n")
            written += 1
    return written
