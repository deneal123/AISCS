"""Encode experimental forced-graph events for checked downstream replay."""

from __future__ import annotations

import hashlib

import numpy as np

from service.infrastructure.stimulation.synaptic_replay import select_recorded_spikes


def encode_forced_spikes(graph, network):
    """Encode exactly the graph IDs and event arrays; do not infer physiology.

    The checksum must be preserved alongside the returned description. This
    self-consistency checksum does not authenticate the experiment provenance.
    """
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
    arrays = (("node_ids", ids.astype("<u8", copy=False)),
              ("spike_neurons", indices.astype("<i4", copy=False)),
              ("spike_times_ms", times.astype("<f4", copy=False)))
    layout, blocks, offset = {}, [], 0
    for name, array in arrays:
        data = array.tobytes(order="C")
        blocks.append(data)
        layout[name] = {"dtype": array.dtype.str, "offset": offset, "count": len(array),
                        "shape": [len(array)]}
        offset += len(data)
    binary = b"".join(blocks)
    description = {"manifest_sha256": graph.provenance["manifest_sha256"],
                   "duration_ms": duration,
                   "binary": {"byte_order": "little", "bytes": len(binary), "arrays": layout},
                   "interpretation": "experimental one-way forced graph; "
                                     "not physiological evidence"}
    return binary, description, hashlib.sha256(binary).hexdigest()
