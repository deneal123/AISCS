"""Detecting a noxious input from behaviour alone.

The question the operator actually asks is behavioural: given only what the animal
did, can you tell that the input was noxious? That question has a trap in it, and the
trap is leakage. If the label is "escaped" and a feature is the escape latency, the
detector reads the answer off the label. If a feature is the recruited afferent count
or the spike count, the detector reads the stimulus, not the behaviour, and the whole
exercise proves nothing about behaviour.

This module therefore fixes three rules before any number is produced:

  * the label is the PROTOCOL fact -- whether the applied current was at or above the
    measured noxious threshold -- and never a body measurement;
  * the features are the body block only: displacement, abdominal curl, height, and
    the muscle recruitment that moved them. No stimulus, no spike count, no recruited
    count, no cell identity. assert_no_leakage fails the run if a forbidden column is
    named;
  * the evaluation is grouped by stimulus site. Episodes at one site are not
    independent -- the site decides which afferents are recruited -- so a random split
    would score the detector on near-duplicates. Every fold holds one whole site out.

What the numbers mean and do not mean is stated in the result: an AUC above chance
says behaviour carries the information that the input was noxious. It does not say the
animal felt anything, and the receipt repeats that.
"""

from __future__ import annotations

from collections import Counter  # noqa: F401  (kept for callers that count labels)

import numpy as np

FORMAT = "malecns-behavioural-noxious-detection-v1"

BODY_FEATURES = ("displacement_mm", "displacement_x_mm", "displacement_z_mm", "curl_change_rad", "peak_height_cm", "min_height_cm", "height_drop_cm", "curl_per_ms", "displacement_per_ms")
# Which way the animal went. Not in DEFAULT_FEATURES on purpose: the detection numbers
# in report 31 were measured without it, and adding a feature silently re-writes them.
# A caller that wants the turn asks for these two by name.
TURN_FEATURES = ("turn_deg", "abs_turn_deg")
MUSCLE_FEATURES = ("motor_spikes", "motor_spikes_per_ms", "motor_heard",
                   "mapped_first_tick_ms")
FLIGHT_FEATURES = ("wing_spikes", "airborne_cm", "lift_to_weight", "beating")
DEFAULT_FEATURES = BODY_FEATURES + MUSCLE_FEATURES + FLIGHT_FEATURES


FORBIDDEN = ("current_na", "recruited_afferents", "source_cell_count", "spike_count",
             "active_cells", "site_um", "compound_action", "escape_latency_ms")


def _body(record):
    return record.get("body") or {}


def behaviour_features(record, features=DEFAULT_FEATURES):
    """One row of behavioural features, zeros where the twin measured nothing.

    A missing latency becomes 0.0 and is paired with the motor_heard flag, because a
    sentinel of -1 would be read by a linear model as "earlier than any real value" and a
    latency of zero never occurs: measured latencies are 9-12 ms.
    """
    body = _body(record)
    duration = float(record.get("duration_ms") or 1.0)
    flight = body.get("flight") or {}
    curl = float(body.get("curl_change_rad") or 0.0)
    displacement = float(body.get("displacement_mm") or 0.0)
    peak = float(body.get("peak_height_cm") or 0.0)
    low = float(body.get("min_height_cm") or 0.0)
    motor = int(body.get("motor_spikes") or 0)
    latency = body.get("mapped_first_tick_ms")
    turn = float(body.get("turn_deg") or 0.0)
    row = {
        "turn_deg": turn,
        "abs_turn_deg": abs(turn),
        "displacement_mm": displacement,
        "displacement_x_mm": float(body.get("displacement_x_mm") or 0.0),
        "displacement_z_mm": float(body.get("displacement_z_mm") or 0.0),
        "curl_change_rad": curl,
        "peak_height_cm": peak,
        "min_height_cm": low,
        "height_drop_cm": peak - low,
        "curl_per_ms": curl / duration,
        "displacement_per_ms": displacement / duration,
        "motor_spikes": float(motor),
        "motor_spikes_per_ms": motor / duration,
        "motor_heard": 0.0 if latency is None else 1.0,
        "mapped_first_tick_ms": 0.0 if latency is None else float(latency),
        "wing_spikes": float(flight.get("wing_spikes") or 0),
        "airborne_cm": float(flight.get("airborne_cm") or 0.0),
        "lift_to_weight": float(flight.get("lift_to_weight") or 0.0),
        "beating": 1.0 if flight.get("beating") else 0.0,
    }
    return {name: float(row[name]) for name in features}


def assert_no_leakage(features):
    """Refuse a feature list that would read the stimulus or the label."""
    bad = [name for name in features if name in FORBIDDEN]
    if bad:
        raise ValueError("A behavioural detector may not read " + ", ".join(bad))


NOXIOUS_CURRENT_NA = -3600.0


def is_noxious(record, threshold_na=NOXIOUS_CURRENT_NA):
    """The protocol fact the detector is asked to recover from behaviour."""
    current = record.get("current_na")
    return current is not None and float(current) <= float(threshold_na)


def matrix(records, features=DEFAULT_FEATURES):
    """Feature matrix plus the two labels, so a caller can aim at either."""
    assert_no_leakage(features)
    rows = [behaviour_features(record, features) for record in records]
    values = np.asarray([[row[name] for name in features] for row in rows], dtype=float)
    noxious = np.asarray([1 if is_noxious(record) else 0 for record in records], dtype=int)
    escaped = np.asarray([1 if (_body(record).get("escape_latency_ms") is not None) else 0
                          for record in records], dtype=int)
    return values, noxious, escaped


def site_of(record):
    site = record.get("site_um") or (0.0, 0.0, 0.0)
    return ",".join(f"{float(v):.1f}" for v in site)


def detect(records, *, target="noxious", features=DEFAULT_FEATURES):
    """Leave-one-site-out detection with a permutation control.

    The model is a standardiser plus a balanced logistic regression: with a few dozen
    episodes anything larger would fit the site identity rather than the behaviour. The
    permutation control shuffles the labels and reruns the same folds, so a pooled AUC
    that only reflects class imbalance shows up as a permutation AUC near 0.5.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if target not in ("noxious", "escaped"):
        raise ValueError("Invalid detection target")
    values, noxious, escaped = matrix(records, features)
    labels = noxious if target == "noxious" else escaped
    sites = np.asarray([site_of(record) for record in records])
    unique = sorted(set(sites.tolist()))
    if len(unique) < 2:
        raise ValueError("Detection needs at least two stimulus sites to hold one out")

    def folds(flags):
        scores = np.zeros(len(flags), dtype=float)
        seen = np.zeros(len(flags), dtype=bool)
        per_fold = {}
        for site in unique:
            test = sites == site
            train = ~test
            if len(set(flags[train].tolist())) < 2 or not test.any():
                per_fold[site] = {"test": int(test.sum()), "skipped": "single-class train"}
                continue
            model = make_pipeline(StandardScaler(),
                                  LogisticRegression(max_iter=2000,
                                                     class_weight="balanced"))
            model.fit(values[train], flags[train])
            scores[test] = model.predict_proba(values[test])[:, 1]
            seen[test] = True
            per_fold[site] = {"test": int(test.sum()),
                              "positives": int(flags[test].sum()),
                              "auc": _auc(scores[test], flags[test])}
        return scores, seen, per_fold

    scores, seen, per_fold = folds(labels)
    pooled = _auc(scores[seen], labels[seen])
    usable = [row["auc"] for row in per_fold.values() if row.get("auc") is not None]
    rng = np.random.default_rng(7)
    permuted = []
    for _ in range(20):
        shuffled = rng.permutation(labels)
        shuffled_scores, shuffled_seen, _ = folds(shuffled)
        permuted.append(_auc(shuffled_scores[shuffled_seen], shuffled[shuffled_seen]))
    permuted = [value for value in permuted if value is not None]
    return {
        "format": FORMAT,
        "target": target,
        "episodes": int(len(labels)),
        "positives": int(labels.sum()),
        "sites": len(unique),
        "features": list(features),
        "pooled_auc": pooled,
        "mean_fold_auc": (float(np.mean(usable)) if usable else None),
        "folds": per_fold,
        "permutation_auc_mean": (float(np.mean(permuted)) if permuted else None),
        "permutation_auc_max": (float(np.max(permuted)) if permuted else None),
        "feature_means_by_class": _means(values, labels, features),
        "leakage_rule": ("features are the body block only; the label is the applied "
                         "current, never a body measurement"),
        "not_a_feeling": ("an AUC above chance says behaviour carries the information "
                          "that the input was noxious; it is not a claim about a feeling "
                          "and says nothing about experience"),
    }


DOSE_FEATURES = ("curl_change_rad", "displacement_mm", "motor_spikes", "abs_turn_deg")


def dose_ranking(records, *, features=DOSE_FEATURES, threshold_na=NOXIOUS_CURRENT_NA):
    """Does the body rank the dose, inside one preparation?

    This is a different question from detect(). detect() asks whether behaviour tells a
    noxious episode from a sub-threshold one, holding a whole stimulus site out, so the
    detector can never see the site it is scored on. That is the right test for a
    detector that will meet a new preparation, and it is also a hard test, because the
    site decides which afferents fire: two episodes at different sites with the same
    current are not the same stimulus at all.

    A dose-response experiment asks something narrower and in some ways more useful:
    inside ONE preparation, as the current is raised, does the body move more? No site
    is held out because there is only one, and the score is a single named feature with
    no fitting, so nothing is estimated from the labels. What it cannot do is separate
    the effect of the dose from the identity of the site, and the receipt says so.
    """
    assert_no_leakage(features)
    by_site = {}
    for record in records:
        by_site.setdefault(site_of(record), []).append(record)
    per_site = {}
    ranked = []
    for site, group in sorted(by_site.items()):
        labels = np.asarray([1 if is_noxious(r, threshold_na) else 0 for r in group])
        row = {"episodes": len(group), "above_threshold": int(labels.sum())}
        if labels.min() == labels.max():
            row["skipped"] = "single class"
            per_site[site] = row
            continue
        for feature in features:
            scores = np.asarray([behaviour_features(r, (feature,))[feature] for r in group])
            auc = _auc(scores, labels)
            row[feature] = None if auc is None else round(float(auc), 4)
            if auc is not None:
                ranked.append(max(auc, 1.0 - auc))
        per_site[site] = row
    return {
        "format": FORMAT,
        "target": "dose_within_site",
        "features": list(features),
        "sites": len(by_site),
        "mean_site_auc": (round(float(np.mean(ranked)), 4) if ranked else None),
        "per_site": per_site,
        "not_a_feeling": ("a body that ranks the dose is not a body that feels it; the "
                          "score is one kinematic feature and the site is not held out"),
    }


def _means(values, labels, features):
    out = {}
    for flag, name in ((1, "noxious"), (0, "below_threshold")):
        rows = values[labels == flag]
        if not len(rows):
            continue
        out[name] = {feature: round(float(rows[:, index].mean()), 5)
                     for index, feature in enumerate(features)}
    return out


def _auc(scores, labels):
    """Rank AUC with ties averaged; None when either side is empty."""
    pairs = sorted(zip(np.asarray(scores, dtype=float).tolist(), labels.tolist()))
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
    return float((rank_sum - positives * (positives + 1) / 2.0)
                 / (positives * negatives))


def summary(result):
    """One line a report can quote without re-reading the folds."""
    return {
        "format": result["format"],
        "target": result["target"],
        "episodes": result["episodes"],
        "positives": result["positives"],
        "sites": result["sites"],
        "pooled_auc": (None if result["pooled_auc"] is None
                       else round(result["pooled_auc"], 4)),
        "mean_fold_auc": (None if result["mean_fold_auc"] is None
                          else round(result["mean_fold_auc"], 4)),
        "permutation_auc": (None if result["permutation_auc_mean"] is None
                            else round(result["permutation_auc_mean"], 4)),
    }
