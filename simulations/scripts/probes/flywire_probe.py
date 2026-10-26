"""Exercise pinned network-analysis helpers and selected v630 notebook analyses."""

import hashlib
import importlib.metadata
import itertools
import json
import sys
import time
from pathlib import Path

import graph_tool.all as gt
import matplotlib
import networkx as nx
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = Path("/work/source")
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(BASE / "python_scripts/FlywireAnalysis"))
from utils import graph_creation as gc
from utils import measure
from utils import motif_counts as mc
from utils import utils as gu


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(obj), flush=True)


def signature(graph):
    edges = graph.get_edges()[:, :2]
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    return hashlib.sha256(edges[order].astype("<i8").tobytes()).hexdigest()


def software():
    checks = []
    frame = pd.DataFrame({"pre": [0, 0, 1, 2, 3], "post": [1, 1, 0, 2, 0]})
    simple = gc.edges_to_graph(frame)
    multi = gc.edges_to_graph(frame, multi=True)
    assert simple.number_of_edges() == 4 and multi.number_of_edges() == 5
    assert gc.remove_autapses(simple).number_of_edges() == 3
    checks.append("simple/multi edge semantics and autapse removal")
    recurrent = gc.get_recurrent_graph(nx.DiGraph([(0, 1), (1, 0), (1, 2)]))
    assert set(recurrent.nodes) == {0, 1}
    checks.append("iterative removal of zero-outdegree vertices")
    assert measure.rand_index_score(np.array([0, 0, 1, 1]), np.array([0, 0, 1, 1])) == 1
    assert np.isclose(measure.r2([0, 1, 2], [1, 3, 5]), 1)
    checks.append("Rand index and squared Pearson correlation fixtures")
    # Exhaust all 64 labelled directed loop-free graphs on three vertices.
    pairs = list(itertools.permutations(range(3), 2))
    mapping = {}
    for key, motif in mc.motifs.items():
        g = nx.DiGraph()
        g.add_nodes_from(range(3))
        g.add_edges_from(motif.edges)
        mapping[key] = next(k for k, v in nx.triadic_census(g).items() if v)
    assert len(set(mapping.values())) == 16
    for mask in range(64):
        g = nx.DiGraph()
        g.add_nodes_from(range(3))
        g.add_edges_from(e for i, e in enumerate(pairs) if mask & (1 << i))
        counts, _ = mc.count_three_neuron_motifs(set(g.nodes), set(g.edges), mc.motifs)
        census = nx.triadic_census(g)
        assert all(counts[key] == census[label] for key, label in mapping.items())
    checks.append("all 64 directed three-vertex motifs against NetworkX triadic census")
    # Diagnose, do not silently repair, the upstream integer-attribute conversion.
    ids = [720575940600000000, 720575940600000001]
    graph = nx.DiGraph()
    graph.add_node(ids[0], root_id=ids[0])
    graph.add_node(ids[1], root_id=ids[1])
    graph.add_edge(*ids)
    converted = gu.nx2gt(graph)
    stored = [int(converted.vp["root_id"][v]) for v in converted.vertices()]
    identity = list(converted.vp["id"])
    assert identity == list(map(str, ids))
    save(
        "software.json",
        {
            "checks": checks,
            "native_test_suite": False,
            "scope": "independent software fixtures calling unchanged author helpers",
            "integer_attribute_diagnostic": {
                "input": ids,
                "stored_root_id": stored,
                "node_id_strings": identity,
                "attribute_preserved_exactly": stored == ids,
                "reason": "upstream get_prop_type maps Python int attributes to float",
                "notebook_main_route": "explicit int64 cellid property, checked separately",
            },
            "motif_mapping": mapping,
        },
    )


def inspect():
    import seaborn
    from utils import mfas, visualization

    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "numpy",
            "pandas",
            "scipy",
            "matplotlib",
            "networkx",
            "seaborn",
            "pyintergraph",
        )
    }
    save(
        "environment.json",
        {
            "python": sys.version,
            "graph_tool": gt.__version__,
            "packages": versions,
            "headless": True,
            "imports": [mfas.__name__, visualization.__name__, seaborn.__name__],
            "scope": "modern official runtime; no author environment lock",
        },
    )


def figures(graph, sweep, regions, null_runs):
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    for kind, color in (("in", "#205d89"), ("out", "#c46635")):
        degree = (
            graph.get_in_degrees(graph.get_vertices())
            if kind == "in"
            else graph.get_out_degrees(graph.get_vertices())
        )
        x, n = np.unique(degree, return_counts=True)
        axes[0].loglog(x[x > 0], n[x > 0], ".", markersize=3, color=color, label=kind)
    axes[0].set(
        xlabel="Distinct partners (degree)",
        ylabel="Number of neurons",
        title="FlyWire v630: merged graph",
    )
    axes[0].legend()
    axes[1].plot(
        [r["threshold"] for r in sweep],
        [r["largest_scc"] for r in sweep],
        "o-",
        label="Strong component",
    )
    axes[1].plot(
        [r["threshold"] for r in sweep],
        [r["largest_wcc"] for r in sweep],
        "s-",
        label="Weak component",
    )
    axes[1].set(
        xlabel="Minimum synapses per directed pair",
        ylabel="Neurons in largest component",
        title="Weight threshold, all vertices retained",
    )
    axes[1].legend(fontsize=9)
    region = regions.sort_values("syn_count", ascending=False).head(12).iloc[::-1]
    axes[2].barh(region.index, region.syn_count / 1e6, color="#205d89")
    axes[2].set(
        xlabel="Summed synapse counts (millions)",
        title="Top neuropils in registered export",
    )
    fig.suptitle(
        "SIM-017 | Structural analyses only; not simulated neural activity", fontsize=13
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("v630-network." + suffix), dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    fig.subplots_adjust(left=0.11, right=0.97, top=0.87, bottom=0.22)
    labels = ["Observed AL_R"] + [f"CFG seed {r['seed']}" for r in null_runs]
    values = [null_runs[0]["observed_reciprocity"]] + [
        r["reciprocity"] for r in null_runs
    ]
    ax.bar(labels, values, color=["#205d89"] + ["#9aaeb9"] * 4)
    ax.set(
        ylabel="Directed edge reciprocity",
        title="AL_R edge-defined graph: degree-preserving controls",
    )
    fig.text(
        0.5,
        0.01,
        "Repeated seed 1 checks reproducibility; four runs are not an inferential null ensemble.",
        ha="center",
        fontsize=9,
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("v630-controls." + suffix), dpi=160)
    plt.close(fig)


def full():
    started = time.monotonic()
    manifest = json.loads(Path("/work/v630-inputs.json").read_text())
    # Same notebook graph definition; typed arrays replace per-edge Python tuples.
    dtype = {"pre_root_id": "int64", "post_root_id": "int64", "syn_count": "int64"}
    table = pd.read_csv(
        BASE / "v630_data/connections.csv.gz",
        dtype=dtype,
        usecols=["pre_root_id", "post_root_id", "neuropil", "syn_count"],
    )
    assert table["syn_count"].gt(0).all()
    ids = np.unique(table[["pre_root_id", "post_root_id"]].to_numpy().reshape(-1))
    table["pre_nid"] = np.searchsorted(ids, table["pre_root_id"].to_numpy())
    table["post_nid"] = np.searchsorted(ids, table["post_root_id"].to_numpy())
    merged = (
        table.groupby(["pre_nid", "post_nid"], sort=True)["syn_count"]
        .sum()
        .reset_index()
    )
    graph = gt.Graph(directed=True)
    graph.add_vertex(len(ids))
    weights = graph.new_ep("int64_t")
    graph.add_edge_list(merged.to_numpy(dtype=np.int64), eprops=[weights])
    graph.ep["syn_count"] = weights
    graph.vp["cellid"] = graph.new_vp("int64_t", vals=ids)
    assert np.array_equal(graph.vp["cellid"].a, ids)
    assert int(weights.a.sum()) == int(table.syn_count.sum())
    sweep = []
    for threshold in (1, 3, 5, 10, 15, 20, 30, 50):
        graph.set_edge_filter(graph.new_ep("bool", vals=weights.a >= threshold))
        _, scc = gt.label_components(graph, directed=True)
        _, wcc = gt.label_components(graph, directed=False)
        row = {
            "threshold": threshold,
            "edges": int(graph.num_edges()),
            "largest_scc": int(scc.max()),
            "largest_wcc": int(wcc.max()),
            "reciprocity": float(gt.edge_reciprocity(graph)),
        }
        assert all(np.isfinite(v) for v in row.values())
        sweep.append(row)
        print("threshold", row, flush=True)
        graph.clear_filters()
    pd.DataFrame(
        {
            "root_id": ids,
            "in_degree": graph.get_in_degrees(graph.get_vertices()),
            "out_degree": graph.get_out_degrees(graph.get_vertices()),
        }
    ).to_csv(OUT / "v630-node-degrees.csv", index=False)
    pd.DataFrame(sweep).to_csv(OUT / "v630-thresholds.csv", index=False)
    regions = table.groupby("neuropil")["syn_count"].agg(["sum", "count"])
    regions.columns = ["syn_count", "export_rows"]
    regions.to_csv(OUT / "v630-neuropils.csv")
    # Predeclared AL_R edge subset, not an induced graph of all AL_R-labelled neurons.
    region = table[table.neuropil == "AL_R"]
    reg = region.groupby(["pre_nid", "post_nid"])["syn_count"].sum().reset_index()
    reg_ids = np.unique(reg[["pre_nid", "post_nid"]].to_numpy().reshape(-1))
    edges = np.column_stack(
        [np.searchsorted(reg_ids, reg.pre_nid), np.searchsorted(reg_ids, reg.post_nid)]
    )
    local = gt.Graph(directed=True)
    local.add_vertex(len(reg_ids))
    local.add_edge_list(edges)
    observed = float(gt.edge_reciprocity(local))
    in_degree = local.get_in_degrees(local.get_vertices())
    out_degree = local.get_out_degrees(local.get_vertices())
    null_runs = []
    for seed in (1, 2, 3, 1):
        t = time.monotonic()
        trial = local.copy()
        gt.seed_rng(seed)
        # One complete edge sweep, not a claim of null-ensemble mixing/convergence.
        gt.random_rewire(
            trial,
            model="configuration",
            n_iter=1,
            self_loops=False,
            parallel_edges=False,
        )
        assert np.array_equal(in_degree, trial.get_in_degrees(trial.get_vertices()))
        assert np.array_equal(out_degree, trial.get_out_degrees(trial.get_vertices()))
        assert trial.num_edges() == local.num_edges()
        null_runs.append(
            {
                "seed": seed,
                "sha256_sorted_edges": signature(trial),
                "reciprocity": float(gt.edge_reciprocity(trial)),
                "observed_reciprocity": observed,
                "seconds": time.monotonic() - t,
                "degree_preserved": True,
            }
        )
    assert null_runs[0]["sha256_sorted_edges"] == null_runs[3]["sha256_sorted_edges"]
    # Exercise author motif helper on this real anatomical edge subset.
    network = nx.DiGraph(edges.tolist())
    counts = mc.count_two_neuron_motifs_graph(network)
    assert nx.number_of_selfloops(network) == 0
    reciprocal_pairs = sum(network.has_edge(v, u) for u, v in network.edges) // 2
    singles = network.number_of_edges() - 2 * reciprocal_pairs
    empty_pairs = len(network) * (len(network) - 1) // 2 - singles - reciprocal_pairs
    assert counts["null"] == empty_pairs
    assert counts["uni"] == singles and counts["bi"] == reciprocal_pairs
    annotations = {}
    for item in manifest["files"]:
        if item["file"] == "connections.csv.gz":
            continue
        frame = pd.read_csv(BASE / "v630_data" / item["file"])
        assert frame.root_id.notna().all()
        annotations[item["file"]] = {
            "rows": len(frame),
            "columns": len(frame.columns),
            "unique_root_ids": int(frame.root_id.nunique()),
            "root_ids_outside_connection_endpoints": int(
                (~frame.root_id.isin(ids)).sum()
            ),
        }
    figures(graph, sweep, regions, null_runs)
    graph.save(str(OUT / "v630-merged.gt.gz"))
    summary = {
        "scope": "selected original notebook analyses, not whole-paper reproduction",
        "dataset": "FlyWire v630",
        "input_rows": len(table),
        "neurons_with_edges": len(ids),
        "merged_directed_edges": int(graph.num_edges()),
        "synapse_count_sum": int(table.syn_count.sum()),
        "minimum_export_row_syn_count": int(table.syn_count.min()),
        "minimum_merged_pair_syn_count": int(weights.a.min()),
        "autapses": int(gt.label_self_loops(graph).a.sum()),
        "root_ids_exact_int64": True,
        "thresholds": sweep,
        "annotations": annotations,
        "al_r": {
            "vertices": int(local.num_vertices()),
            "edges": int(local.num_edges()),
            "two_neuron_motifs": counts,
            "degree_preserving_trials": null_runs,
            "seed1_exact_repeat": True,
        },
        "representation_changes": [
            "typed edge arrays rather than Python tuple lists",
            "int64 weights rather than notebook int32",
        ],
        "not_checked": [
            "all author notebooks and MATLAB cluster analyses",
            "proximity model / rich-club inferential ensemble",
            "compiled Python 3.7 extensions / new ABI",
            "biological activity, body, stimulation, ECAP",
        ],
        "units": {
            "edge_weight": "synapse count",
            "degree": "distinct partners",
            "time_step": "not applicable: structural analysis",
        },
        "seconds": time.monotonic() - started,
    }
    save("functional.json", summary)


if __name__ == "__main__":
    {"software": software, "inspect": inspect, "full": full}[sys.argv[1]]()
