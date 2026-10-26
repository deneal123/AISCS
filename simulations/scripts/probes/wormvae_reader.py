"""Read worm recordings and model exports without importing their numerical runtime."""

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

from flyvis_reader import read_array


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    run = Path(parser.parse_args().run).resolve()
    assert (
        run.parent
        == Path(__file__).resolve().parents[3]
        / "research/.work/simulator-evaluation/SIM-032"
    )
    out = run / "exports"
    result = json.loads((out / "functional.json").read_text())
    assert result["status"] == "passed"
    records = []
    digests = {}
    graph_names = None
    for item in result["cases"]:
        with zipfile.ZipFile(out / (item["name"] + ".npz")) as archive:
            state, shape, digest = read_array(archive, "state")
            times, _, _ = read_array(archive, "times_s")
            names, _, _ = read_array(archive, "names")
        assert shape == (101, result["nodes"]) and list(shape) == item["shape"]
        assert all(math.isfinite(x) for x in state)
        assert digest == item["array_sha256"]
        assert all(abs(t - i * 0.00625) < 1e-12 for i, t in enumerate(times))
        assert len(names) == len(set(names)) == result["nodes"]
        if graph_names is None:
            graph_names = names
        assert names == graph_names
        digests[item["name"]] = digest
        records.append({"name": item["name"], "values": len(state)})
    for kind, constraint in [
        ("conductance", "weight"),
        ("conductance", "sparsity"),
        ("conductance", "unconstrained"),
        ("current", "sparsity"),
        ("current", "unconstrained"),
    ]:
        prefix = kind + "-" + constraint
        assert digests[prefix + "-seed-1"] == digests[prefix + "-seed-1-repeat"]
    with zipfile.ZipFile(out / "recorded-inputs.npz") as archive:
        data, shape, _ = read_array(archive, "fluorescence")
        odors, odor_shape, _ = read_array(archive, "odors")
        measured_names, _, _ = read_array(archive, "names")
    assert shape == (21, 189, 800) and odor_shape == (21, 3, 800)
    assert set(measured_names) <= set(graph_names)
    assert all(math.isfinite(x) or math.isnan(x) for x in data)
    assert all(math.isfinite(x) for x in odors)
    observed = {
        (index // 800) % 189 for index, value in enumerate(data) if math.isfinite(value)
    }
    result = {
        "status": "passed",
        "runtime_imports": False,
        "checked": records,
        "repeat_seed_equal": True,
        "measured_fluorescence_values": len(data),
        "explicit_missing_measurements": sum(math.isnan(x) for x in data),
        "distinct_measured_neurons": len(set(measured_names)),
        "loader_columns_with_any_observation": len(observed),
        "node_map_sha256": hashlib.sha256("\n".join(graph_names).encode()).hexdigest(),
        "scope": "Untrained model state checks are separate from observed calcium fluorescence; no voltage calibration or paper performance reproduced",
    }
    (out / "independent-readback.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
