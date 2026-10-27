"""Compact, checksummed, typed scene buffers plus lossless scientific exports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from service.shared.json_io import write_json


def export_connectome(payload: dict, directory: Path) -> dict:
    arrays, metadata = payload["arrays"], payload["metadata"]
    np.savez_compressed(directory / "connectome-states.npz", **arrays)
    pq.write_table(
        pa.table({"neuron_index": arrays["spike_neurons"], "time_ms": arrays["spike_times_ms"]}),
        directory / "connectome-spikes.parquet",
    )
    layouts = {}
    with (directory / "connectome.bin").open("wb") as stream:
        for name in (
            "node_ids",
            "positions_mm",
            "coordinate_kind",
            "regions",
            "edge_pre",
            "edge_post",
            "edge_sign",
            "spike_neurons",
            "spike_times_ms",
            "counts",
            "input_indices",
        ):
            value = np.ascontiguousarray(arrays[name])
            # Every view starts on an 8-byte boundary for browser typed arrays.
            stream.write(b"\x00" * ((-stream.tell()) % 8))
            layouts[name] = {
                "offset": stream.tell(),
                "dtype": value.dtype.str,
                "shape": list(value.shape),
                "count": value.size,
            }
            stream.write(value.tobytes())
    description = {
        **metadata,
        "spikes_by_ms": np.bincount(
            arrays["spike_times_ms"].astype(int), minlength=int(metadata["duration_ms"]) + 1
        ).tolist(),
        "limitations": metadata["limitations"] + metadata["scene"]["limitations"],
        "binary": {
            "file": "connectome.bin",
            "byte_order": "little",
            "bytes": (directory / "connectome.bin").stat().st_size,
            "arrays": layouts,
        },
        "recording_scope": (
            "Six generic HH proxy cells driven by VNC population events; "
            "not a full-CNS extracellular forward solution."
        ),
        "recognition_scope": "Local-chain v1 classifier is not validated for this preset.",
    }
    write_json(directory / "connectome.json", description)
    return description
