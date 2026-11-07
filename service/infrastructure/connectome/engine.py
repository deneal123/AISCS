"""Whole-CNS dynamics with an explicit engineering projection to the local recorder."""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
from time import perf_counter

from service.contracts import SimulationConfig
from service.infrastructure.connectome.dataset import MANIFEST_SHA256, load_registered_graph
from service.infrastructure.connectome.notum import NotumGraph
from service.infrastructure.connectome.scene import scene_arrays
from service.infrastructure.connectome.solver import simulate_hybrid
from service.infrastructure.neuron.solver import NeuronEngine, simulate
from service.settings import connectome_directory


def dataset_directory() -> Path:
    return connectome_directory()


class RegisteredEngine:
    def simulate(self, config: SimulationConfig):
        if config.model_id == "local-compartment-chain-v1":
            return simulate(config)
        started = perf_counter()
        graph = load_registered_graph(dataset_directory())
        input_graph = (
            NotumGraph(graph, dataset_directory()) if config.stimulus_region == "notum" else graph
        )
        dynamics, network = simulate_hybrid(config, input_graph)
        if config.stimulus_region == "notum":
            network.metadata["input_population"] = (
                "vnc_sensory / mechanosensory_tactile / notum / PDMN"
            )
        arrays, scene = scene_arrays(graph, network.counts)
        dynamics.connectome = {
            "arrays": {
                **arrays,
                "spike_neurons": network.spike_neurons,
                "spike_times_ms": network.spike_times_ms,
                "counts": network.counts,
                "final_voltage_relative_mv": network.final_voltage_relative_mv,
                "final_synaptic_drive_mv": network.final_synaptic_drive_mv,
                "input_indices": network.input_indices,
            },
            "metadata": {**network.metadata, "scene": scene},
        }
        dynamics.seconds = perf_counter() - started
        return dynamics

    @staticmethod
    def identity() -> dict:
        paths = [
            "dataset.py",
            "network.py",
            "solver.py",
            "kernel.py",
            "scene.py",
            "engine.py",
            "body-routes.json",
            "notum.py",
        ]
        directory = Path(__file__).parent
        return {
            **NeuronEngine.identity(),
            "adapter": "registered-local-or-male-cns-v1",
            "connectome_manifest_sha256": MANIFEST_SHA256,
            "numba": importlib.metadata.version("numba"),
            "llvmlite": importlib.metadata.version("llvmlite"),
            "connectome_adapter_sha256": hashlib.sha256(
                b"".join((directory / p).read_bytes() for p in paths)
            ).hexdigest(),
            "state_schema": "dynamics-with-whole-cns-v1",
        }


class RecordingEvaluationEngine:
    """Same complete numerical network; omits display buffers during evaluation."""

    def __init__(self, graph=None):
        self.graph = graph if graph is not None else load_registered_graph(dataset_directory())

    def simulate(self, config: SimulationConfig):
        started = perf_counter()
        input_graph = (
            NotumGraph(self.graph, dataset_directory())
            if config.stimulus_region == "notum"
            else self.graph
        )
        dynamics, _ = simulate_hybrid(config, input_graph)
        dynamics.seconds = perf_counter() - started
        return dynamics
