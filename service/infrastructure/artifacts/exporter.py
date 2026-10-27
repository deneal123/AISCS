"""Self-describing scientific artifacts, hashes, physical units and immutable configuration."""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from service.contracts import SimulationConfig
from service.domain.catalog import LIMITATIONS
from service.domain.model import Dynamics
from service.domain.recording_noise import add_noise
from service.domain.visualization import VISUALIZATION, compartment_events
from service.infrastructure.lfpy.recording import forward_recording
from service.shared.json_io import write_json


def export_result(config: SimulationConfig, dynamics: Dynamics, directory: Path) -> dict:
    if config.model_id == "male-cns-hybrid-v1" and not dynamics.connectome:
        raise ValueError("Full-CNS export requires the complete registered network payload")
    directory.mkdir(parents=True, exist_ok=True)
    clean = forward_recording(config, dynamics)
    signal = add_noise(clean, config.seed, config.noise_uv)
    table = pa.table({"time_ms": dynamics.time_ms, "signal_uv": signal, "clean_signal_uv": clean})
    pq.write_table(table, directory / "signals.parquet")
    import pyarrow.csv as csv

    csv.write_csv(table, directory / "signals.csv")
    np.savez_compressed(
        directory / "states.npz",
        time_ms=dynamics.time_ms,
        membrane_current_na=dynamics.membrane_current_na,
        voltage_mv=dynamics.voltage_mv,
        starts_um=dynamics.starts_um,
        ends_um=dynamics.ends_um,
        diameters_um=dynamics.diameters_um,
        cell_ids=dynamics.cell_ids,
        soma_segment_ids=dynamics.soma_segment_ids,
        input_event_time_ms=np.array([e["time_ms"] for e in dynamics.input_events or []]),
        input_event_cell_ids=np.array(
            [e["cell_id"] for e in dynamics.input_events or []], dtype=int
        ),
        input_event_weight_us=np.array([e["weight_us"] for e in dynamics.input_events or []]),
    )
    write_json(directory / "configuration.json", config.model_dump())
    write_json(directory / "neural-events.json", dynamics.spikes)
    write_json(
        directory / "geometry.json",
        {
            "origin": "author-defined schematic; not biological reconstruction",
            "units": "um",
            "starts_um": dynamics.starts_um.tolist(),
            "ends_um": dynamics.ends_um.tolist(),
            "diameters_um": dynamics.diameters_um.tolist(),
            "cell_ids": dynamics.cell_ids.tolist(),
            "soma_segment_ids": dynamics.soma_segment_ids,
            "transform_version": "thoracic-rigid-v1",
        },
    )
    indices = np.unique(np.linspace(0, len(signal) - 1, min(2001, len(signal))).astype(int))
    from service.infrastructure.recognition.classifier import predict

    connectome = None
    if dynamics.connectome:
        from service.infrastructure.connectome.export import export_connectome

        connectome = export_connectome(dynamics.connectome, directory)
    visualization = VISUALIZATION
    if connectome:
        visualization = {
            **VISUALIZATION,
            "input": {
                **VISUALIZATION["input"],
                "kind": "VNC-population-to-HH-projection-v1",
                "max_event_weight_us": 0.02,
            },
        }
        from service.infrastructure.recognition.connectome_classifier import predict_connectome

        prediction, prediction_status = predict_connectome(dynamics.time_ms, signal, config)
    else:
        prediction, prediction_status = predict(dynamics.time_ms, signal), None

    write_json(
        directory / "preview.json",
        {
            "time_ms": dynamics.time_ms[indices].tolist(),
            "signal_uv": signal[indices].tolist(),
            "soma_voltage_mv": dynamics.voltage_mv[dynamics.soma_segment_ids][:, indices].tolist(),
            "spikes": dynamics.spikes,
            **(
                {"input_events": dynamics.input_events} if dynamics.input_events is not None else {}
            ),
            "compartment_events": compartment_events(dynamics.time_ms, dynamics.voltage_mv),
            "visualization": visualization,
            "sample_count": len(signal),
            "downsampled": len(indices) != len(signal),
            "geometry": {
                "starts_um": dynamics.starts_um.tolist(),
                "ends_um": dynamics.ends_um.tolist(),
                "cell_ids": dynamics.cell_ids.tolist(),
                "diameters_um": dynamics.diameters_um.tolist(),
                "soma_segment_ids": dynamics.soma_segment_ids,
            },
            "prediction": prediction,
            **({"prediction_status": prediction_status} if prediction_status else {}),
            **({"connectome": connectome} if connectome else {}),
        },
    )
    metrics = {
        "solver_seconds": dynamics.seconds,
        "dynamics_cache": dynamics.cache_info,
        "registration": config.placement.model_dump(),
        "samples": len(signal),
        "spike_count": len(dynamics.spikes),
        "rms_uv": float(np.sqrt(np.mean(signal**2))),
        "peak_to_peak_uv": float(np.ptp(signal)),
        "dt_ms": config.dt_ms,
        **({"connectome": dynamics.connectome["metadata"]} if connectome else {}),
    }
    write_json(directory / "metrics.json", metrics)
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(dynamics.time_ms, signal, lw=0.7)
    ax.set(
        xlabel="Model time (ms)", ylabel="E1 - REF (uV)", title="Synthetic local-model recording"
    )
    fig.tight_layout()
    fig.savefig(directory / "signal.svg")
    fig.savefig(directory / "signal.png", dpi=150)
    plt.close(fig)
    import resource

    metrics["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    write_json(directory / "metrics.json", metrics)
    files = []
    for path in sorted(directory.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "contract_version": "1.0",
        "configuration_sha256": config.digest(),
        "dynamics_sha256": config.dynamics_digest(),
        "registration": config.placement.model_dump(mode="json"),
        "visualization": visualization,
        "files": files,
        "metrics": metrics,
        "units": {"time": "ms", "signal": "uV", "current": "nA", "position": "um"},
        "versions": {
            p: importlib.metadata.version(p)
            for p in ["NEURON", "LFPy", "lfpykit", "numpy"]
            + (["numba", "llvmlite"] if connectome else [])
        },
        "dynamics_cache": dynamics.cache_info,
        **(
            {
                "recognition": {
                    **prediction_status,
                    **(
                        {
                            "model_id": prediction["model_id"],
                            "model_sha256": prediction["model_sha256"],
                            "scope": prediction["scope"],
                        }
                        if prediction
                        else {}
                    ),
                }
            }
            if connectome
            else {}
        ),
        "operator": {
            "name": "lfpy-pointsource-e1-minus-ref-v1",
            "source_sha256": hashlib.sha256(
                Path(__file__).parents[1].joinpath("lfpy/recording.py").read_bytes()
            ).hexdigest(),
            "medium": "infinite homogeneous isotropic conductor",
            "conductivity_s_m": config.conductivity_s_m,
        },
        "limitations": LIMITATIONS
        + (connectome["limitations"] + [connectome["recording_scope"]] if connectome else []),
        **({"connectome": connectome} if connectome else {}),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


class ArtifactWriter:
    write = staticmethod(export_result)
