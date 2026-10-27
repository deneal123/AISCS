from collections.abc import Callable
from time import perf_counter

import numpy as np

from service.contracts import SimulationConfig
from service.domain.geometry import sections_for_cell
from service.domain.model import Dynamics


def simulate(
    config: SimulationConfig,
    progress: Callable[[float], None] | None = None,
    *,
    projected_events: list[dict] | None = None,
) -> Dynamics:
    from neuron import h

    started = perf_counter()
    h.load_file("stdrun.hoc")
    for old in list(h.allsec()):
        h.delete_section(sec=old)
    h.CVode().use_fast_imem(1)
    rng = np.random.default_rng(config.seed)
    sections, somas, segments, starts, ends, diameters, cell_ids = [], [], [], [], [], [], []
    soma_ids = []
    for cell in range(6):
        soma = h.Section(name=f"cell{cell}_soma")
        dendrite = h.Section(name=f"cell{cell}_dendrite")
        axon = h.Section(name=f"cell{cell}_axon")
        dendrite.connect(soma(0))
        axon.connect(soma(1))
        local = {"soma": soma, "dendrite": dendrite, "axon": axon}
        for kind, first, last, diameter, count in sections_for_cell(cell):
            sec = local[kind]
            sec.Ra, sec.cm, sec.nseg = 100, 1, count
            h.pt3dclear(sec=sec)
            h.pt3dadd(*first, diameter, sec=sec)
            h.pt3dadd(*last, diameter, sec=sec)
            sec.insert("hh")
            for seg in sec:
                seg.hh.gnabar = 0.12 * config.excitability
                seg.hh.gkbar = 0.036 * (1 + config.adaptation * 0.25)
            start, end = np.asarray(first), np.asarray(last)
            for i, seg in enumerate(sec):
                segments.append(seg)
                starts.append(start + (end - start) * i / count)
                ends.append(start + (end - start) * (i + 1) / count)
                diameters.append(diameter)
                cell_ids.append(cell)
            sections.append(sec)
        soma_ids.append(len(segments) - 15 + 1)
        somas.append(soma)

    synapses, connections = [], []
    for i in range(5):
        syn = h.ExpSyn(somas[i + 1](0.5))
        syn.tau, syn.e = 2, 0
        conn = h.NetCon(somas[i](0.5)._ref_v, syn, sec=somas[i])
        conn.threshold, conn.delay, conn.weight[0] = -10, 1.5, 0.004
        synapses.append(syn)
        connections.append(conn)

    drives = []
    weight = {"none": 0, "weak": 0.0025, "strong": 0.009}[config.stimulus]
    for soma in somas[:2] if projected_events is None else []:
        syn = h.ExpSyn(soma(0.5))
        syn.tau, syn.e = 2, 0
        connection = h.NetCon(None, syn)
        connection.weight[0] = weight * (1 - config.adaptation * 0.3)
        drives.append((syn, connection))

    projected_drives = []
    for event in projected_events or []:
        cell, when, weight_us = event["cell_id"], event["time_ms"], event["weight_us"]
        if type(cell) is not int or not 0 <= cell < 6 or not 0 < when < config.duration_ms:
            raise ValueError("Invalid population projection event")
        if not np.isfinite(weight_us) or not 0 <= weight_us <= 0.02:
            raise ValueError("Invalid projected conductance")
        syn = h.ExpSyn(somas[cell](0.5))
        syn.tau, syn.e = 2, 0
        connection = h.NetCon(None, syn)
        connection.weight[0] = weight_us
        projected_drives.append((event, syn, connection))

    time = h.Vector().record(h._ref_t)
    voltages = [h.Vector().record(seg._ref_v) for seg in segments]
    currents = [h.Vector().record(seg._ref_i_membrane_) for seg in segments]
    h.dt, h.steps_per_ms, h.celsius = config.dt_ms, 1 / config.dt_ms, 23
    h.finitialize(-65)
    # Event timing varies by seed; the same seed/config reproduces the same realization.
    input_events = []
    for cell, (_, connection) in enumerate(drives):
        for event in np.arange(25, config.duration_ms - 15, 18):
            scheduled = float(event + rng.uniform(-2, 2))
            connection.event(scheduled)
            input_events.append(
                {
                    "cell_id": cell,
                    "time_ms": scheduled,
                    "weight_us": float(connection.weight[0]),
                }
            )
    # Each event owns its weight. NetCon weights cannot be overwritten before
    # delivery when events with different conductances target the same cell.
    for event, _, connection in projected_drives:
        connection.event(event["time_ms"])
        input_events.append(dict(event))
    steps = round(config.duration_ms / config.dt_ms)
    for step in range(steps):
        h.fadvance()
        if progress and step % 800 == 0:
            progress(step / steps)
    t = np.asarray(time).copy()
    voltage = np.array([np.asarray(v) for v in voltages])
    current = np.array([np.asarray(v) for v in currents])
    if not np.isfinite(voltage).all() or not np.isfinite(current).all():
        raise ValueError("Non-finite NEURON state")
    spikes = []
    for cell, idx in enumerate(soma_ids):
        crossing = np.where((voltage[idx, :-1] < -10) & (voltage[idx, 1:] >= -10))[0] + 1
        spikes.extend({"cell_id": cell, "time_ms": float(t[i])} for i in crossing)
    return Dynamics(
        t,
        voltage,
        current,
        np.array(starts),
        np.array(ends),
        np.array(diameters),
        np.array(cell_ids),
        soma_ids,
        spikes,
        perf_counter() - started,
        input_events=input_events,
    )


class NeuronEngine:
    simulate = staticmethod(simulate)

    @staticmethod
    def identity() -> dict:
        import hashlib
        import importlib.metadata
        from pathlib import Path

        return {
            "adapter": "neuron-local-chain-v1",
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "geometry_sha256": hashlib.sha256(
                Path(__file__).parents[2].joinpath("domain/geometry.py").read_bytes()
            ).hexdigest(),
            "NEURON": importlib.metadata.version("NEURON"),
            "numpy": np.__version__,
            "state_schema": "dynamics-nA-mV-ms-um-input-events-v2",
        }
