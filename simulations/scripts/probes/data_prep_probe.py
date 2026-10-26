"""Run the pinned larval notebook's matrix operations on its actual registered data."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy as sp
from scipy.sparse import coo_matrix

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
DATA = Path("data/larva")
NOTEBOOK = Path("larva_prepare_connectome.ipynb")


def notebook():
    data = NOTEBOOK.read_bytes().replace(b"\r\n", b"\n")
    oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert oid == "dc41ebdb3de50f477147281b516b080163a9c655"
    return json.loads(data)


def run_cell(code, label, scope):
    # Only explicitly selected cells from the hash-verified pinned notebook above.
    exec(compile(code, str(NOTEBOOK) + ":" + label, "exec"), scope)  # noqa: S102


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n")


def smoke():
    document = notebook()
    assert len(document["cells"]) > 36
    rows = []
    for name in [
        "larva_ad_syncount.npz",
        "larva_ad_inprop.npz",
        "larva_all_syncount.npz",
        "larva_all_inprop.npz",
    ]:
        matrix = sp.sparse.load_npz(DATA / name)
        assert (
            matrix.shape[0] == matrix.shape[1]
            and np.isfinite(matrix.data).all()
            and (matrix.data >= 0).all()
        )
        rows.append(
            {
                "file": name,
                "shape": list(matrix.shape),
                "nnz": matrix.nnz,
                "dtype": str(matrix.dtype),
            }
        )
    save(
        "smoke.json",
        {
            "status": "passed",
            "matrices": rows,
            "entry_point": "selected notebook cells; repository has no general simulator CLI",
            "python": sys.version,
        },
    )


def software():
    # Native notebook normalization and sparse round trip, independently checked.
    cases = []
    for kind in ["ad", "all"]:
        counts = sp.sparse.load_npz(DATA / ("larva_" + kind + "_syncount.npz")).tocsc()
        original = sp.sparse.load_npz(DATA / ("larva_" + kind + "_inprop.npz")).tocsc()
        totals = np.asarray(counts.sum(axis=0)).reshape(-1)
        inverse = np.divide(1.0, totals, out=np.zeros(totals.shape), where=totals != 0)
        recomputed = counts.multiply(inverse).astype(np.float32).tocsc()
        difference = (original - recomputed).tocoo()
        maximum = float(np.abs(difference.data).max()) if difference.nnz else 0.0
        assert maximum < 1e-6
        sums = np.asarray(original.sum(axis=0)).reshape(-1)
        assert np.allclose(sums[totals > 0], 1, atol=1e-6)
        assert not np.any(sums[totals == 0])
        sp.sparse.save_npz(OUT / ("checked-" + kind + ".npz"), recomputed)
        reread = sp.sparse.load_npz(OUT / ("checked-" + kind + ".npz"))
        assert (reread != recomputed).nnz == 0
        cases.append(
            {
                "kind": kind,
                "shape": list(counts.shape),
                "nnz": counts.nnz,
                "zero_input_columns": int((totals == 0).sum()),
                "normalization_max_abs_difference": maximum,
                "repeat_equal": True,
            }
        )
    save(
        "software.json",
        {
            "status": "passed",
            "native_suite": False,
            "checks": cases,
            "scope": "exact registered processed matrices; not biological dynamics or a complete rerun of all dataset downloads",
            "zero_column_handling": "own comparison initializes inverse zeros explicitly; author reciprocal(where=...) omits out and leaves excluded values unspecified",
        },
    )


def full():
    cells = notebook()["cells"]
    code = {index: "".join(cells[index]["source"]) for index in [6, 10, 11, 14]}
    ad = pd.read_csv("data/ad_connectivity_matrix.csv", index_col=0)
    assert ad.shape[0] == ad.shape[1]
    # Only the AD half of cell6 is selected. The all-all raw CSV is not supplied;
    # its processed outputs are checked separately and never substituted for raw.
    selected = code[6].split("conn_edgelist =")[0]
    scope = {"ad": ad, "np": np, "coo_matrix": coo_matrix}
    run_cell(selected, "cell6-AD", scope)
    run_cell(code[10], "cell10", scope)
    # Native set order is process-dependent. Preserve this run's mapping, then
    # compare matrices by explicit biological skid IDs instead of array positions.
    run_cell(code[11], "cell11", scope)
    counts = scope["csc"]
    run_cell(code[14], "cell14", scope)
    inprop = scope["inprop"].tocsc()
    assert np.isfinite(inprop.data).all()
    order = [None] * len(scope["nodes_to_idx"])
    for key, index in scope["nodes_to_idx"].items():
        order[index] = key
    assert len(order) == len(set(order))
    # Independent direct indexing of the dense raw matrix checks orientation.
    direct = ad.copy()
    direct.index = direct.index.astype(str)
    direct.columns = direct.columns.astype(str)
    direct = direct.reindex(index=order, columns=order, fill_value=0)
    assert (counts != sp.sparse.csc_matrix(direct.values)).nnz == 0
    sp.sparse.save_npz(OUT / "native-rebuilt-ad-counts.npz", counts)
    sp.sparse.save_npz(OUT / "native-rebuilt-ad-inprop.npz", inprop)
    pd.DataFrame({"index": np.arange(len(order)), "skid": order}).to_csv(
        OUT / "native-node-order.csv", index=False
    )
    meta = pd.read_csv(DATA / "larva_all_neuron_meta.csv", dtype={"skid": str})
    supplied = sp.sparse.load_npz(DATA / "larva_ad_syncount.npz").tocsc()
    indexed = meta.dropna(subset=["idx"]).copy()
    indexed["idx"] = indexed["idx"].astype(int)
    mapping = dict(zip(indexed.skid, indexed.idx, strict=True))
    matched = [key for key in order if key in mapping]
    assert len(matched) == len(order), (
        "Raw matrix IDs do not all map to registered metadata"
    )
    assert len({mapping[key] for key in order}) == len(order)
    permutation = [mapping[key] for key in order]
    aligned = supplied[permutation, :][:, permutation]
    assert (aligned != counts).nnz == 0
    # Replay exact native cells with the SAME explicit mapping, independent of set order.
    repeat_scope = dict(scope)
    run_cell(code[11], "repeat-cell11", repeat_scope)
    assert (repeat_scope["csc"] != counts).nnz == 0
    save(
        "functional.json",
        {
            "status": "passed",
            "nodes": counts.shape[0],
            "nnz": counts.nnz,
            "native_cells": ["6 AD half", "10", "11", "14"],
            "raw_matrix_verified_by_independent_orientation": True,
            "registered_matrix_equal_after_id_alignment": True,
            "repeat_equal": True,
            "node_map_sha256": hashlib.sha256(
                (OUT / "native-node-order.csv").read_bytes()
            ).hexdigest(),
            "scope": "larval axon-dendrite preparation only; no all-all raw file, adult datasets, dynamics, body or human ECAP",
            "orientation": "row presynaptic, column postsynaptic; inprop normalized by recipient input",
            "seeds": "not a stochastic simulator; native set order preserved in explicit mapping",
            "limitations": [
                "full notebook includes author-local paths and an unpinned live metadata URL",
                "no repository license file or locked environment",
                "connectome_interpreter is not used by selected preparation cells; other analysis notebooks not executed",
            ],
        },
    )
    import subprocess

    subprocess.run(
        [sys.executable, "/work/probes/data_prep_plot.py"], check=True, timeout=120
    )


if __name__ == "__main__":
    {"smoke": smoke, "software": software, "full": full}[sys.argv[1]]()
