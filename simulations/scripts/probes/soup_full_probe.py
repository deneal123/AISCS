"""Try the author's full MaleCNS converter and fixed-point CPU runtime."""

import csv
import hashlib
import json
import os
import random
import shutil
import sys
import time
from array import array
from pathlib import Path

from soup_connectome.config import SimulationConfig
from soup_connectome.graph.format import open_artifact
from soup_connectome.graph.malecns import MaleCNSColumns, convert_male_cns
from soup_connectome.sim.runtime import run_graph

OUT = Path("/work/exports/full-male-cns")
OUT.mkdir(parents=True, exist_ok=True)
HOST_CACHE = Path("/work/cache")
CACHE = Path(os.environ.get("ASPA_SOUP_SCRATCH", "/work/cache"))
if CACHE not in (HOST_CACHE, Path("/tmp/aspa-soup")):
    raise ValueError(
        "Scratch must be the owned run cache or private container temporary tree"
    )
CACHE.mkdir(exist_ok=True)
ASSETS = Path("/work/assets/malecns")
ARTIFACT = CACHE / "male-cns-v1.0-annotated.scx"
INPUTS = {
    "body-annotations.feather": "2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2",
    "body-nt.feather": "95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621",
    "connectome-weights.feather": "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


assert sys.byteorder == "little"
for name, digest in INPUTS.items():
    assert sha(ASSETS / name) == digest, name
save(
    "inputs.json",
    {
        "version": "MaleCNS v1.0 minconf 0.5",
        "sha256": INPUTS,
        "network_downloads": 0,
        "scope": "registered primary exports reused",
    },
)
started = time.monotonic()
host_artifact = HOST_CACHE / ARTIFACT.name
mode = sys.argv[1] if len(sys.argv) > 1 else "all"
if mode not in ("all", "prepare", "run"):
    raise ValueError("Unknown scenario")
if CACHE != HOST_CACHE and not ARTIFACT.exists() and host_artifact.is_dir():
    shutil.copytree(host_artifact, ARTIFACT)
if mode == "run" and not ARTIFACT.is_dir():
    raise ValueError("A completed registered artifact is required before dynamics")
if not ARTIFACT.exists():
    print("Starting full registered MaleCNS conversion", flush=True)
    report = convert_male_cns(
        ASSETS / "connectome-weights.feather",
        ASSETS / "body-annotations.feather",
        ASSETS / "body-nt.feather",
        ARTIFACT,
        columns=MaleCNSColumns(
            annotation_id="bodyId",
            annotation_type="type",
            annotation_side="somaSide",
            neurotransmitter_id="body",
            neurotransmitter_name="consensus_nt",
        ),
        sign_mapping={"acetylcholine": 1, "gaba": -1, "glutamate": 1},
        excluded_neurotransmitters=(
            "unclear",
            "dopamine",
            "histamine",
            "octopamine",
            "serotonin",
            "unknown",
        ),
        block_size=100000,
        node_filter="annotations",
    )
    save(
        "conversion.json",
        {
            "status": "passed",
            "seconds": time.monotonic() - started,
            "neurons": report.n_neurons,
            "edges": report.n_edges,
            "excluded_edges": report.excluded_edges,
            "saturated_weights": report.saturated_weights,
            "scope": "author README conversion; sign assumptions are not biological validation",
        },
    )
manifest = json.loads((ARTIFACT / "manifest.json").read_text())
conversion = manifest["conversion"]
assert conversion["weights_sha256"] == INPUTS["connectome-weights.feather"]
assert conversion["annotations_sha256"] == INPUTS["body-annotations.feather"]
assert conversion["neurotransmitters_sha256"] == INPUTS["body-nt.feather"]
assert conversion["node_filter"] == "annotations"
assert conversion["sign_mapping"] == {"acetylcholine": 1, "gaba": -1, "glutamate": 1}
save("artifact-manifest.json", manifest)
for descriptor in manifest["blocks"]:
    assert sha(ARTIFACT / descriptor["filename"]) == descriptor["sha256"]
assert sha(ARTIFACT / "neurons.bin") == manifest["neurons_sha256"]
if CACHE != HOST_CACHE and not host_artifact.exists():
    shutil.copytree(ARTIFACT, host_artifact)
    for descriptor in manifest["blocks"]:
        assert sha(host_artifact / descriptor["filename"]) == descriptor["sha256"]
    assert sha(host_artifact / "neurons.bin") == manifest["neurons_sha256"]
graph = open_artifact(ARTIFACT)
assert graph.n_neurons > 0 and graph.edge_count > 0
with (OUT / "neurons.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(
        ("dense_index", "external_id", "type_code", "transmitter_code", "side_code")
    )
    writer.writerows(
        (i, n.external_id, n.type_code, n.transmitter_code, n.side_code)
        for i, n in enumerate(graph.neurons)
    )
if mode == "prepare":
    print("Full artifact prepared", graph.n_neurons, graph.edge_count, flush=True)
    sys.exit(0)
config = SimulationConfig(
    threshold=20000, reset=0, decay_shifts=(2,), refractory_steps=2
)
start = time.monotonic()
quiet = run_graph(
    graph,
    config,
    timesteps=1,
    initial_potentials=(0,) * graph.n_neurons,
    residency="streamed",
)
assert quiet.spike_count == 0 and all(v == 0 for v in quiet.final_potentials)
save(
    "quiet.json",
    {"status": "passed", "seconds": time.monotonic() - start, "steps": 1, "spikes": 0},
)
del quiet
trials = []
first = None
for attempt, seed in enumerate((1, 2, 3, 1)):
    # Seed selects the input site; the integer runtime itself is deterministic.
    site = 0 if seed == 1 else random.Random(seed).randrange(graph.n_neurons)
    initial = [0] * graph.n_neurons
    initial[site] = 30000
    started = time.monotonic()
    result = run_graph(
        graph,
        config,
        timesteps=4,
        initial_potentials=tuple(initial),
        residency="streamed",
    )
    elapsed = time.monotonic() - started
    assert len(result.spikes) == 4 and all(
        len(t) == graph.n_neurons for t in result.spikes
    )
    assert len(result.final_potentials) == graph.n_neurons
    assert all(
        type(v) is int and -(2**31) <= v < 2**31 for v in result.final_potentials
    )
    voltages = array("i", result.final_potentials).tobytes()
    spikes = bytes(int(v) for step in result.spikes for v in step)
    refractory = array("I", result.final_refractory).tobytes()
    if attempt == 0:
        first = (voltages, spikes, refractory)
    if attempt == 3:
        assert first == (voltages, spikes, refractory)
    prefix = f"seed{seed}-attempt{attempt}"
    for name, data in (
        ("potential-int32le.bin", voltages),
        ("spikes-u8.bin", spikes),
        ("refractory-uint32le.bin", refractory),
    ):
        (OUT / (prefix + "-" + name)).write_bytes(data)
    trial = {
        "seed": seed,
        "input_index": site,
        "input_external_id": graph.neurons[site].external_id,
        "initial_potential": 30000,
        "seconds": elapsed,
        "spikes_per_step": [sum(step) for step in result.spikes],
        "potential_sha256": hashlib.sha256(voltages).hexdigest(),
        "spikes_sha256": hashlib.sha256(spikes).hexdigest(),
    }
    trials.append(trial)
    save("trials-progress.json", {"completed": trials})
    print("Full graph trial", json.dumps(trial), flush=True)
save(
    "functional.json",
    {
        "status": "passed",
        "scope": "full registered MaleCNS fixed-point CPU runtime, not biological validation",
        "neurons": graph.n_neurons,
        "edges": graph.edge_count,
        "steps": 4,
        "potential_unit": "fixed-point integer, not mV",
        "time_unit": "discrete step, not ms",
        "delay_steps": conversion["delay_steps"],
        "config": config.model_dump(mode="json"),
        "repeat_seed_equal": True,
        "zero_input_quiescent": True,
        "trials": trials,
    },
)
