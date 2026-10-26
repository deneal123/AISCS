"""Independently reconstruct the tested synapse total from the primary CSV files."""

import csv
import gzip
import json
import re
import sys
import time
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from inventory import save
    from simctl import checked_work

    run = checked_work(Path(sys.argv[1]))
    started = time.monotonic()
    evidence = json.loads((run / "exports/optic-lobe/full-result.json").read_text())
    t1 = set(evidence["t1_root_ids"])
    with gzip.open(run / "data/Codex neuron IDs/neurons.csv.gz", "rt") as f:
        roots = {row["root_id"] for row in csv.DictReader(f)}
    path = (
        run
        / "data/Codex Princeton connections no threshold/connections_princeton_no_threshold.csv.gz"
    )
    total = removed_t1 = rows = outside = autapses = 0
    with gzip.open(path, "rt") as f:
        for row in csv.DictReader(f):
            rows += 1
            pre, post = row["pre_root_id"], row["post_root_id"]
            count = int(row["syn_count"])
            if pre not in roots or post not in roots:
                outside += count
            elif pre == post:
                autapses += count
            else:
                total += count
                if pre in t1:
                    removed_t1 += count
    computed = total - removed_t1
    assert computed == evidence["synapses"], (
        "Independent CSV result contradicts the loaded Julia graph"
    )
    test = (run / "source/test/runtests.jl").read_text()
    expected = int(re.search(r"total_synapses == (\d+)", test)[1])
    receipt = {
        "status": "diagnosed",
        "seconds": time.monotonic() - started,
        "connection_rows": rows,
        "neuron_ids": len(roots),
        "current_T1_cells": len(t1),
        "synapses_outside_neuron_ids": outside,
        "autapses_removed": autapses,
        "after_autapse_removal": total,
        "T1_outgoing_removed": removed_t1,
        "independent_filtered_total": computed,
        "julia_filtered_total": evidence["synapses"],
        "independent_total_matches_julia": True,
        "native_expected": expected,
        "native_expected_matches": computed == expected,
        "difference_from_native_expectation": computed - expected,
        "interpretation": "The native control total disagrees after T1 filtering. Historical T1 assignments were not recovered; no exact cell-level change history is claimed.",
        "scientific_validation": False,
    }
    save(run / "independent-data-diagnostic.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
