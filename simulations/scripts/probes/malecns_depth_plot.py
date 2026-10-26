"""Plot actual prepared graph statistics; this is not a neural-activity trace."""

import hashlib
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    run = Path(sys.argv[1]).resolve()
    output = run / "exports/malecns-depth"
    evidence = json.loads((output / "real-graph-result.json").read_text())
    assert evidence["status"] == "passed" and evidence["repeat_content_equal"]
    expected = evidence["trials"][0]
    digest = hashlib.sha256()
    with np.load(run / "assets/malecns/neuron_edges.npz", allow_pickle=False) as data:
        arrays = {name: data[name] for name in ("pre", "post", "w", "body_ids")}
    for name, values in arrays.items():
        assert np.isfinite(values).all()
        digest.update(name.encode())
        digest.update(str(values.dtype).encode())
        digest.update(np.ascontiguousarray(values).tobytes())
    assert digest.hexdigest() == expected["content_sha256"]
    n = len(arrays["body_ids"])
    assert (
        n == expected["neurons"] and len(arrays["w"]) == expected["connectivity_rows"]
    )
    assert int(arrays["w"].sum()) == expected["synapse_weight_sum"]
    incoming = np.bincount(arrays["post"], minlength=n)
    outgoing = np.bincount(arrays["pre"], minlength=n)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for values, label in ((incoming, "Incoming"), (outgoing, "Outgoing")):
        positive = np.sort(values[values > 0])
        axes[0].plot(positive, np.arange(len(positive), 0, -1) / n, label=label)
    axes[0].set(
        xscale="log",
        yscale="log",
        xlabel="Directed partners per neuron",
        ylabel="Fraction with at least this many partners",
        title="Real MaleCNS v1.0: graph degree",
    )
    axes[0].legend()
    weights = arrays["w"]
    bins = np.unique(np.geomspace(1, int(weights.max()) + 1, 50).astype(int))
    axes[1].hist(weights, bins=bins, color="#365b85")
    axes[1].set(
        xscale="log",
        yscale="log",
        xlabel="Synapse count per directed edge",
        ylabel="Number of edges",
        title="Anatomical edge weights, not activity",
    )
    fig.suptitle(
        f"{n:,} neurons; {len(weights):,} edges; {int(weights.sum()):,} synapses"
    )
    for extension in ("png", "svg"):
        fig.savefig(output / ("graph-statistics." + extension), dpi=160)
    plt.close(fig)
    (output / "visual-provenance.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "graph_content_sha256": digest.hexdigest(),
                "source_result": "real-graph-result.json",
                "scope": "Structural graph statistics only; not neural dynamics, locomotion or ECAP",
                "zero_indegree": int((incoming == 0).sum()),
                "zero_outdegree": int((outgoing == 0).sum()),
                "matplotlib": matplotlib.__version__,
                "numpy": np.__version__,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
