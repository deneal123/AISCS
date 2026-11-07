"""Encode experimental forced-graph events for checked downstream replay."""

from __future__ import annotations

import hashlib

import numpy as np

from service.infrastructure.stimulation.synaptic_replay import select_recorded_spikes


def _validated_arrays(graph, network):
    if not isinstance(network, dict) or not isinstance(network.get("metadata"), dict):
        raise ValueError("Invalid forced network")
    metadata = network["metadata"]
    if metadata.get("graph") != graph.provenance:
        raise ValueError("Forced network graph provenance differs")
    duration = metadata.get("duration_ms")
    if type(duration) is not int or not 1 <= duration <= 1000:
        raise ValueError("Invalid network duration")
    ids = np.asarray(graph.ids)
    indices = np.asarray(network.get("spike_neurons"))
    times = np.asarray(network.get("spike_times_ms"))
    select_recorded_spikes(ids, indices, times, [])
    if np.any(times > duration):
        raise ValueError("Spike outside network duration")
    arrays = (("node_ids", ids, np.dtype("<u8")),
              ("spike_neurons", indices, np.dtype("<i4")),
              ("spike_times_ms", times, np.dtype("<f4")))
    layout, offset = {}, 0
    for name, array, dtype in arrays:
        layout[name] = {"dtype": dtype.str, "offset": offset, "count": len(array),
                        "shape": [len(array)]}
        offset += len(array) * dtype.itemsize
    description = {"manifest_sha256": graph.provenance["manifest_sha256"],
                   "duration_ms": duration,
                   "binary": {"byte_order": "little", "bytes": offset, "arrays": layout},
                   "interpretation": "experimental one-way forced graph; "
                                     "not physiological evidence"}
    return arrays, description


def encode_forced_spikes(graph, network):
    """Encode the graph and events in memory for callers that require bytes."""
    arrays, description = _validated_arrays(graph, network)
    binary = b"".join(array.astype(dtype, copy=False).tobytes(order="C")
                      for _, array, dtype in arrays)
    return binary, description, hashlib.sha256(binary).hexdigest()


def write_forced_spikes(path, graph, network, *, chunk_items=262144):
    """Write the identical checked format in bounded chunks, without a full copy.

    The caller must retain the description and digest as trusted provenance.
    Never replace an existing file; remove a partial file on write failure.
    """
    if type(chunk_items) is not int or chunk_items <= 0:
        raise ValueError("Invalid event export chunk size")
    arrays, description = _validated_arrays(graph, network)
    digest = hashlib.sha256()
    with path.open("xb") as stream:
        try:
            for _, array, dtype in arrays:
                for start in range(0, len(array), chunk_items):
                    block = np.ascontiguousarray(array[start:start + chunk_items], dtype=dtype)
                    data = memoryview(block).cast("B")
                    if stream.write(data) != len(data):
                        raise OSError("Incomplete event export")
                    digest.update(data)
        except BaseException:
            stream.close()
            path.unlink(missing_ok=True)
            raise
    return description, digest.hexdigest()
