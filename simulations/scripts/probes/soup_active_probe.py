"""Author-described active fixed-point stress case, not biological calibration."""

import hashlib
import json
import shutil
import time
from array import array
from pathlib import Path

from soup_connectome.config import SimulationConfig
from soup_connectome.graph.format import open_artifact
from soup_connectome.sim.runtime import run_graph

source = Path("/work/cache/male-cns-v1.0-annotated.scx")
local = Path("/tmp/aspa-active.scx")
shutil.copytree(source, local)
graph = open_artifact(local)
config = SimulationConfig(threshold=1, reset=0, decay_shifts=(31,), refractory_steps=0)
initial = [0] * graph.n_neurons
initial[0] = 30000
out = Path("/work/exports/full-male-cns")
trials = []
reference = None
for attempt in range(2):
    started = time.monotonic()
    result = run_graph(
        graph,
        config,
        timesteps=2,
        initial_potentials=tuple(initial),
        residency="streamed",
    )
    spikes = bytes(int(value) for step in result.spikes for value in step)
    voltage = array("i", result.final_potentials).tobytes()
    counts = [sum(step) for step in result.spikes]
    assert counts[0] == 1 and counts[1] > 0
    if reference is None:
        reference = (spikes, voltage)
    else:
        assert reference == (spikes, voltage)
    (out / f"active-attempt{attempt}-spikes-u8.bin").write_bytes(spikes)
    (out / f"active-attempt{attempt}-potential-int32le.bin").write_bytes(voltage)
    trial = {
        "attempt": attempt,
        "seconds": time.monotonic() - started,
        "spikes_per_step": counts,
        "spikes_sha256": hashlib.sha256(spikes).hexdigest(),
        "potential_sha256": hashlib.sha256(voltage).hexdigest(),
    }
    trials.append(trial)
    print(json.dumps(trial), flush=True)
receipt = {
    "status": "passed",
    "scope": "author active stress configuration; no calibrated neural time or voltage",
    "neurons": graph.n_neurons,
    "edges": graph.edge_count,
    "config": config.model_dump(mode="json"),
    "steps": 2,
    "input_index": 0,
    "input_external_id": graph.neurons[0].external_id,
    "initial_potential": 30000,
    "repeat_content_equal": True,
    "trials": trials,
    "matches_author_spike_counts": trials[0]["spikes_per_step"] == [1, 319],
}
(out / "active-stress.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
