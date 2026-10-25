"""Exercise upstream CPU fixture semantics; not a biological connectome."""

import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path

from soup_connectome.graph.example import example_graph, example_simulation_config
from soup_connectome.graph.format import load_artifact, open_artifact, write_artifact
from soup_connectome.sim.runtime import run_graph


def run(seed, disk_graph):
    graph = example_graph()
    config = example_simulation_config()
    rng = random.Random(seed)
    initial = (32767, rng.randrange(-1000, 1000), 0, 0)
    result = run_graph(
        graph, config, timesteps=12, initial_potentials=initial, residency="resident"
    )
    streamed = run_graph(
        disk_graph,
        config,
        timesteps=12,
        initial_potentials=initial,
        residency="streamed",
    )
    assert result == streamed
    assert len(result.spikes) == 12 and all(len(row) == 4 for row in result.spikes)
    assert all(type(x) is int for x in result.final_potentials)
    return asdict(result)


target = Path("/work/exports")
target.mkdir(exist_ok=True)
artifact = write_artifact(example_graph(), target / "example.scx")
assert load_artifact(artifact).graph == example_graph()
disk_graph = open_artifact(artifact)
results = {str(seed): run(seed, disk_graph) for seed in [1, 2, 3]}
assert run(1, disk_graph) == results["1"]  # Repeat/reset, no persistent hidden state.
artifact_files = {
    path.relative_to(artifact).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(artifact.rglob("*"))
    if path.is_file()
}
report = {
    "data_scope": "upstream_four_neuron_design_fixture",
    "seed_controls_input": True,
    "neurons": 4,
    "timesteps": 12,
    "time_unit": "discrete_step",
    "potential_unit": "fixed_point_integer_not_mV",
    "repeat_seed_equal": True,
    "resident_streamed_equal": True,
    "results": results,
    "artifact_file_sha256": artifact_files,
    "artifact_sha256": hashlib.sha256(
        json.dumps(artifact_files, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest(),
    "artifact_digest_input": "UTF-8 compact sorted JSON of relative paths and file SHA256 values",
}
(target / "fixture.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        {
            key: report[key]
            for key in [
                "data_scope",
                "neurons",
                "timesteps",
                "repeat_seed_equal",
                "resident_streamed_equal",
            ]
        }
    )
)
