"""Compare the exact two-node browser fixture with the Python CPU implementation."""

import json
from pathlib import Path

from soup_connectome.config import SimulationConfig
from soup_connectome.graph.builder import graph_from_rows
from soup_connectome.graph.format import Edge
from soup_connectome.sim.runtime import run_graph

graph = graph_from_rows(2, [(0, Edge(target=1, weight=8, delay=1))], block_size=2)
config = SimulationConfig(threshold=4, reset=0, decay_shifts=(1,), refractory_steps=0)
result = run_graph(
    graph, config, timesteps=2, initial_potentials=(10, 0), residency="resident"
)
cpu = {
    "spikes": [list(step) for step in result.spikes],
    "finalPotentials": list(result.final_potentials),
    "finalRefractory": list(result.final_refractory),
}
path = Path("/work/exports/browser/browser-fixture.json")
browser = json.loads(path.read_text())
assert browser["status"] == "passed"
assert (
    cpu
    == browser["result"]["expected"]
    == browser["result"]["webgpu"]
    == browser["result"]["wasm"]
)
proof = {
    "status": "passed",
    "scope": "exact same two-node graph, units and initial state across CPU, WebGPU and WASM",
    "cpu": cpu,
    "browser_evidence": "exports/browser/browser-fixture.json",
    "biological_validation": False,
}
Path("/work/cross-backend-parity.json").write_text(
    json.dumps(proof, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(proof))
