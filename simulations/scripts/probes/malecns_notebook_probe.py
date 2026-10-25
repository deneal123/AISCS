"""Exercise the pinned quantification notebook and selected tables without version mixing."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

import google_crc32c
import pandas as pd

SOURCE = Path("/work/source")
DATA = Path("/work/assets/v09")
OUT = Path("/work/exports/malecns-notebook")
NOTEBOOK = SOURCE / "supplemental_data/quantify-neuron-connections.ipynb"


def cells():
    content = json.loads(NOTEBOOK.read_text())
    return ["".join(c["source"]) for c in content["cells"] if c["cell_type"] == "code"]


def counts(ns):
    return {
        "annotations": len(ns["annotations"]),
        "input_weight_rows": len(ns["weights"]),
        "valid_superclasses": len(ns["valid_superclasses"]),
        "valid_types": len(ns["valid_types"]),
        "valid_edges": len(ns["valid_weights"]),
        "valid_nodes": len(ns["valid_weights_neurons"]),
        "thresholded_edges": len(ns["thresholded_valid_weights"]),
        "thresholded_nodes": len(ns["thresholded_valid_weights_neurons"]),
        "type_edges": len(ns["thresholded_type_weights"]),
        "connected_types": ns["thresholded_type_edge_types"],
    }


def execute(folder, supply_os=True, normalize_labels=True):
    namespace = {"__name__": "__evaluation_notebook__"}
    previous = Path.cwd()
    os.chdir(folder)
    try:
        for index, code in enumerate(cells()):
            if index == 2 and normalize_labels:
                # Missing labels are not valid strings; keep all original string predicates.
                assert "if sc and 'tbc' not in sc" in code
                assert "if t and 'unclear' not in t" in code
                code = code.replace(
                    "if sc and 'tbc' not in sc",
                    "if isinstance(sc, str) and 'tbc' not in sc",
                )
                code = code.replace(
                    "if t and 'unclear' not in t",
                    "if isinstance(t, str) and 'unclear' not in t",
                )
            print(f"Executing pinned notebook cell {index}", flush=True)
            # Execute the inspected pinned notebook only inside the isolated container.
            exec(  # noqa: S102 -- reviewed pinned notebook in the isolated execution copy
                compile(code, f"quantify-neuron-connections:cell{index}", "exec"),
                namespace,
            )
            if index == 0 and supply_os:
                namespace["os"] = os
        assert namespace["VERSION"] == "v0.9"
        return counts(namespace)
    finally:
        os.chdir(previous)


def software():
    folder = OUT / "software-fixture"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bodyId": [1, 2, 3, 4, 5, 6],
            "superclass": ["a", "a", "b", "b", "x_tbc", None],
            "type": ["A", "A", "B", "unclear", "Pm7_Li28", None],
        }
    ).to_feather(folder / "body-annotations-male-cns-v0.9-minconf-0.5.feather")
    pd.DataFrame(
        {
            "body_pre": [1, 2, 3, 4, 5, 1],
            "body_post": [2, 3, 4, 1, 1, 99],
            "weight": [3, 5, 7, 2, 10, 6],
        }
    ).to_feather(folder / "connectome-weights-male-cns-v0.9-minconf-0.5.feather")
    try:
        execute(folder, supply_os=False)
    except NameError as exc:
        assert "os" in str(exc)
        baseline = str(exc)
    else:
        raise AssertionError(
            "Expected to reproduce the pinned notebook's missing import"
        )
    try:
        execute(folder, normalize_labels=False)
    except TypeError as exc:
        label_error = str(exc)
    else:
        raise AssertionError(
            "Expected to reproduce missing-label failure in the pinned filter"
        )
    first = execute(folder)
    second = execute(folder)
    assert first == second
    assert first["valid_edges"] == 4 and first["thresholded_edges"] == 2
    assert first["valid_nodes"] == 4 and first["thresholded_nodes"] == 3
    assert first["type_edges"] == 1 and first["connected_types"] == 2
    return {
        "scope": "six-body software fixture, not the biological graph",
        "baseline_error": baseline,
        "missing_label_error": label_error,
        "correction": "Supply import os and apply original string predicates to string labels only",
        "counts": first,
        "repeat_equal": True,
    }


def verify_inputs():
    manifest = json.loads((DATA / "manifest.json").read_text())
    records = []
    for entry in manifest["inputs"]:
        path = DATA / entry["file"]
        sha = hashlib.sha256()
        crc = google_crc32c.Checksum()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                sha.update(chunk)
                crc.update(chunk)
        expected_crc = next(
            x.strip().split("=", 1)[1]
            for x in entry["google_hash"].split(",")
            if x.strip().startswith("crc32c=")
        )
        assert path.stat().st_size == entry["bytes"]
        assert sha.hexdigest() == entry["sha256"]
        assert base64.b64encode(crc.digest()).decode() == expected_crc
        records.append(
            {
                "file": path.name,
                "sha256": sha.hexdigest(),
                "gcs_crc32c_matches": True,
                "generation": entry["generation"],
            }
        )
    assert len(records) == 2
    result = {"dataset": "MaleCNS v0.9", "inputs": records, "status": "passed"}
    (OUT / "input-identity-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Both v0.9 inputs match size, SHA-256 and primary GCS CRC32C", flush=True)
    return result


def supplements():
    results = []
    for path in sorted((SOURCE / "supplemental_data").iterdir()):
        if path.suffix == ".csv":
            frame = pd.read_csv(path)
        elif path.suffix == ".feather":
            frame = pd.read_feather(path)
        elif path.suffix == ".xlsx":
            frame = pd.read_excel(path)
        else:
            continue
        assert len(frame) > 0
        results.append(
            {
                "file": path.name,
                "rows": len(frame),
                "columns": list(frame.columns),
                "null_cells": int(frame.isna().sum().sum()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    assert len(results) == 6
    return {
        "scope": "readability of six pinned supplemental tables, not replay of their production",
        "dataset": "v1.0 supplementary resources; not substituted for notebook v0.9",
        "tables": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["software", "supplements", "full"])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == "software":
        result = software()
    elif args.mode == "supplements":
        result = supplements()
    else:
        inputs = verify_inputs()
        result = {
            "scope": "author notebook on its real pinned v0.9 inputs",
            "inputs": inputs,
            "counts": execute(DATA),
            "correction": "Missing os import supplied; exclude non-string missing labels; VERSION and string predicates unchanged",
            "limitations": [
                "Graph counts, not neural dynamics",
                "No human ECAP or body model",
            ],
        }
    result.update(
        status="passed",
        notebook_sha256=hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest(),
    )
    (OUT / (args.mode + "-result.json")).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
