"""Audit the pinned BANC cascade; real v888 graph, not an invented fly model."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyarrow import feather, parquet

WORK = Path("/work")
SOURCE = WORK / "source/python/cascade model/cascade_model.py"
OUT = (WORK / os.environ.get("ASPA_BANC_EXPORT_DIR", "export")).resolve()
if not OUT.is_relative_to(WORK) or OUT == WORK:
    raise ValueError("BANC export must remain inside its run")
OUT.mkdir(exist_ok=True)


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def module(path):
    spec = importlib.util.spec_from_file_location("banc_cascade", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def fixture():
    return pd.DataFrame(
        {
            "pre": [1, 1, 2, 2],
            "post": [2, 3, 3, 4],
            "effective_count": [10.0, 10.0, 10.0, 10.0],
            "post_count": [10.0, 10.0, 10.0, 10.0],
        }
    )


def verify_inputs():
    manifest = WORK / "banc-inputs.json"
    receipt = json.loads(manifest.read_text())
    verified = []
    for item in receipt["inputs"]:
        path = (WORK / item["file"]).resolve()
        if not path.is_relative_to(WORK) or not path.is_file():
            raise ValueError("Missing or escaping BANC input")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise ValueError("Registered BANC input was modified: " + item["file"])
        verified.append({"file": item["file"], "sha256": actual})
    save(
        "input-verification.json",
        {
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "verified": verified,
        },
    )


def software():
    native = module(SOURCE)
    graph = fixture()
    obj = native.SignalCascade(n_iterations=3, max_timesteps=4)
    adj, ids, _, size = obj.preprocess_edgelist(graph.copy())
    a = native.SignalCascade(p_transmission=0, n_iterations=3, max_timesteps=4)
    b = native.SignalCascade(p_transmission=1, n_iterations=3, max_timesteps=4)
    first = a.run_cascade_v2([1], [], graph.copy())["probabilities"]
    second = b.run_cascade_v2([1], [], graph.copy())["probabilities"]
    negative_graph = pd.DataFrame(
        {"pre": [1], "post": [2], "effective_count": [-10.0], "post_count": [10.0]}
    )
    negative = obj.run_cascade_v2([1], [], negative_graph)["probabilities"]
    cli = subprocess.run(
        [sys.executable, str(SOURCE.with_name("real_data_cascade_main.py")), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    save(
        "original-driver-cli.json",
        {
            "exit_code": cli.returncode,
            "stdout": cli.stdout,
            "stderr": cli.stderr,
            "source_modified": False,
        },
    )
    checks = {
        "identity_dimension_matches_unique_neurons": size == len(ids) == 4,
        "transmission_zero_suppresses_propagation": not bool(first[1:].any()),
        "probabilities_finite_and_bounded": bool(
            np.isfinite(first).all() and (first >= 0).all() and (first <= 1).all()
        ),
        "sources_are_active_at_step_zero": int(first[0].sum()) == 1,
    }
    save(
        "software-checks.json",
        {
            "checks": checks,
            "native_matrix_shape": adj.shape,
            "mapping_size": len(ids),
            "p_zero_equals_p_one": bool(np.array_equal(first, second)),
            "negative_input_alone_activates_target": bool(negative[1:].any()),
            "note": "Own checks of unmodified code; no upstream unit-test suite found. Threshold dynamics, not a validated stochastic synaptic model.",
        },
    )
    print(json.dumps(checks), flush=True)
    return 0 if all(checks.values()) else 1


def smoke():
    verify_inputs()
    module(SOURCE)
    meta = parquet.read_table(WORK / "source/data/meta/banc_888_meta_20260521.parquet")
    edge = feather.read_table(
        WORK / "inputs/banc_888_edgelist_simple_v2.feather", memory_map=True
    )
    save(
        "input-schema.json",
        {
            "metadata_rows": meta.num_rows,
            "metadata_schema": str(meta.schema),
            "edge_rows": edge.num_rows,
            "edge_schema": str(edge.schema),
        },
    )
    print("META", meta.num_rows, meta.column_names, flush=True)
    print("EDGES", edge.num_rows, edge.column_names, flush=True)
    return 0


def identity():
    meta = pd.read_parquet(WORK / "source/data/meta/banc_888_meta_20260521.parquet")
    values = {}
    for key in ("id", "root_id", "root_888", "banc_888_id"):
        if key not in meta:
            continue
        series = meta[key]
        duplicate = series.duplicated(keep=False)
        values[key] = {
            "dtype": str(series.dtype),
            "nulls": int(series.isna().sum()),
            "unique": int(series.nunique()),
            "duplicate_rows": int(duplicate.sum()),
            "examples": series.loc[duplicate].astype(str).head(8).tolist(),
        }
    save("identity-check.json", values)
    print(json.dumps(values), flush=True)
    return 0


def full():
    verify_inputs()
    meta = pd.read_parquet(WORK / "source/data/meta/banc_888_meta_20260521.parquet")
    print("metadata loaded", len(meta), flush=True)
    table = feather.read_table(
        WORK / "inputs/banc_888_edgelist_simple_v2.feather", memory_map=True
    )
    print("edge schema", table.schema, flush=True)
    # Column mappings are intentionally strict; never guess a graph version.
    columns = set(table.column_names)
    pre = next(x for x in ("pre", "pre_root_id", "pre_pt_root_id") if x in columns)
    post = next(x for x in ("post", "post_root_id", "post_pt_root_id") if x in columns)
    count = next(x for x in ("count", "syn_count", "weight") if x in columns)
    normalization = next(x for x in ("post_count", "total_input") if x in columns)
    graph = (
        table.select([pre, post, count, normalization])
        .to_pandas()
        .rename(
            columns={
                pre: "pre",
                post: "post",
                count: "count",
                normalization: "post_count",
            }
        )
    )
    del table
    graph["pre"] = graph["pre"].astype("uint64")
    graph["post"] = graph["post"].astype("uint64")
    total_edges = len(graph)
    total_synapses = int(graph["count"].sum())
    if not (graph["count"] > 0).all():
        raise ValueError("Nonpositive primary synaptic counts")
    incoming = graph.groupby("post", sort=False).agg(
        counted=("count", "sum"),
        declared_min=("post_count", "min"),
        declared_max=("post_count", "max"),
    )
    normalization_check = {
        "post_neurons": len(incoming),
        "inconsistent_denominator_neurons": int(
            (incoming.declared_min != incoming.declared_max).sum()
        ),
        "sum_exceeds_declared_neurons": int(
            (incoming.counted > incoming.declared_min).sum()
        ),
        "sum_below_declared_neurons": int(
            (incoming.counted < incoming.declared_min).sum()
        ),
    }
    save("normalization-check.json", normalization_check)
    if (
        normalization_check["inconsistent_denominator_neurons"]
        or normalization_check["sum_exceeds_declared_neurons"]
    ):
        raise ValueError("Primary incoming normalization is inconsistent")
    del incoming
    # Same >25 threshold used by the author's real-data CLI, before sign mapping.
    if graph.duplicated(["pre", "post"]).any():
        raise ValueError(
            "Duplicate v2 edge pairs; qualify native row-level aggregation before proceeding"
        )
    graph = graph[graph["count"] > 25].copy()
    # The snapshot contains mappings for several materializations. Generic id
    # has merges/duplicates; explicitly join the edge product through root_888.
    key = "root_888"
    valid_metadata = meta[key].notna() & ~meta[key].astype(str).isin(["0", ""])
    excluded_metadata = int((~valid_metadata).sum())
    meta = meta.loc[valid_metadata].copy()
    meta[key] = meta[key].astype("uint64")
    if meta[key].duplicated().any():
        raise ValueError("Ambiguous metadata identity")
    lookup = meta.set_index(key)
    nt = graph["pre"].map(lookup["top_nt"])
    # Do not silently classify missing transmitter as excitatory.
    valid = (
        nt.notna() & graph["pre"].isin(lookup.index) & graph["post"].isin(lookup.index)
    )
    excluded = int((~valid).sum())
    graph = graph.loc[valid].copy()
    graph["effective_count"] = graph["count"] * np.where(
        nt.loc[valid].str.contains("gaba|glutamate", case=False, na=False), -1, 1
    )
    if (
        not np.isfinite(graph["post_count"]).all()
        or not (graph["post_count"] > 0).all()
    ):
        raise ValueError("Invalid anatomical incoming normalization")
    ids = pd.Index(
        pd.unique(pd.concat([graph["pre"], graph["post"]], ignore_index=True))
    )
    metadata = lookup.reindex(ids)
    sensory = (
        metadata["super_class"]
        .astype(str)
        .str.contains("sensory", case=False, na=False)
    )
    source_ids = metadata.index[sensory].tolist()
    if not source_ids:
        raise ValueError("No registered sensory inputs in the selected graph")
    # Repair precisely one observed indexing defect in a derived module, preserve upstream.
    original = SOURCE.read_text()
    old = "pd.Index(edgelist['pre']).union(edgelist['post'])"
    if original.count(old) != 1:
        raise ValueError("Pinned cascade source changed")
    derived = original.replace(old, old + ".unique()")
    adapted = OUT / "cascade_unique_ids.py"
    adapted.write_text(derived)
    save(
        "adapter.json",
        {
            "upstream_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "derived_sha256": hashlib.sha256(adapted.read_bytes()).hexdigest(),
            "replacement": {"from": old, "to": old + ".unique()"},
            "scope": "unique-ID repair only; deterministic native threshold kernel retained",
        },
    )
    native = module(adapted)
    obj = native.SignalCascade(
        n_iterations=2, max_timesteps=8, activation_threshold=0.01
    )
    exports = []
    for seed in (1, 2, 3, 1):
        np.random.seed(seed)
        result = obj.run_cascade_v2(source_ids, [], graph.copy())
        probabilities = result["probabilities"]
        assert probabilities.shape == (8, len(ids))
        assert (
            np.isfinite(probabilities).all()
            and (probabilities >= 0).all()
            and (probabilities <= 1).all()
        )
        exports.append(probabilities.copy())
        print(
            "cascade seed",
            seed,
            "active by step",
            probabilities.sum(axis=1).tolist(),
            flush=True,
        )
    assert np.array_equal(exports[0], exports[3])
    assert all(np.array_equal(exports[0], x) for x in exports[1:])
    # Suppress inputs and terminate at all nodes: explicit intervention checks.
    zero = obj.run_cascade_v2([], [], graph.copy())["probabilities"]
    ended = obj.run_cascade_v2(source_ids, list(ids), graph.copy())["probabilities"]
    assert not zero.any() and not ended[1:].any()
    series = pd.DataFrame(
        {
            "cascade_step": np.arange(8),
            "active_neurons": exports[0].sum(axis=1).astype(int),
        }
    )
    series.to_csv(OUT / "active-by-step.csv", index=False)
    # Export compact per-neuron activation step, retaining exact root identifiers.
    mapped_ids = [str(result["index_to_neuron"][i]) for i in range(len(ids))]
    activated = exports[0].any(axis=0)
    activation_step = np.where(activated, exports[0].argmax(axis=0), -1)
    pd.DataFrame(
        {"root_id": mapped_ids, "first_activation_step": activation_step}
    ).to_csv(OUT / "activation-by-neuron.csv", index=False)
    summary = {
        "materialization": 888,
        "synapse_product": "v2",
        "original_edge_rows": total_edges,
        "original_synapse_count": total_synapses,
        "selected_edges": len(graph),
        "selected_neurons": len(ids),
        "excluded_unknown_identity_or_nt_edges": excluded,
        "metadata_identity_column": key,
        "excluded_metadata_without_v888_root": excluded_metadata,
        "sensory_source_neurons": len(source_ids),
        "seeds": [1, 2, 3, 1],
        "repeat_seed_equal": True,
        "different_seeds_equal": True,
        "dynamics": "deterministic signed linear-threshold; no stochastic draw in native kernel",
        "time_unit": "cascade step; no physical ms mapping",
        "threshold": 0.01,
        "synaptic_threshold": ">25",
        "zero_input_check": True,
        "all_nodes_terminal_check": True,
        "normalization": "original post_count/total_input from the registered edge product; unchanged by filtering",
        "limitations": [
            "Explicit unique-ID adapter",
            "No upstream stochastic transmission implemented",
            "No body, electrophysiological voltage or ECAP",
            "Metadata pinned May 21; edge product last modified June 2; version same, publication co-release not established",
        ],
    }
    save("functional-checks.json", summary)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), layout="constrained")
    axes[0].bar(series.cascade_step, series.active_neurons, color="#255782")
    axes[0].set(
        xlabel="Cascade step (not milliseconds)",
        ylabel="Active neurons",
        title="Sensory-seeded threshold propagation",
    )
    labels = metadata["super_class"].fillna("unassigned").value_counts().head(10)
    axes[1].barh(labels.index[::-1], labels.values[::-1], color="#32877d")
    axes[1].set(
        xlabel="Neurons in selected >25 graph", title="Metadata classes; ten largest"
    )
    fig.suptitle(
        "BANC v888/v2: real graph, native cascade kernel + explicit unique-ID repair"
    )
    for extension in ("png", "svg"):
        fig.savefig(OUT / ("banc-cascade." + extension), dpi=180)
    plt.close(fig)
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(
        {"software": software, "smoke": smoke, "identity": identity, "full": full}[
            sys.argv[1]
        ]()
    )
