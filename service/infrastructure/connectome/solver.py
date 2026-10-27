"""Shared numerical path for UI runs and signal-only recognition evaluation."""

from service.contracts import SimulationConfig
from service.infrastructure.connectome.dataset import SparseGraph
from service.infrastructure.connectome.network import run_network
from service.infrastructure.neuron.solver import simulate


def simulate_hybrid(config: SimulationConfig, graph: SparseGraph):
    if config.model_id != "male-cns-hybrid-v1":
        raise ValueError("The registered hybrid solver requires the MaleCNS preset")
    network = run_network(
        graph,
        seed=config.seed,
        stimulus=config.stimulus,
        region=config.stimulus_region,
        duration_ms=config.duration_ms,
        excitability=config.excitability,
        adaptation=config.adaptation,
    )
    dynamics = simulate(config, projected_events=network.projected_events)
    return dynamics, network
