"""Bounded adjacency from the exact registered graph."""

from functools import lru_cache

import numpy as np

from service.infrastructure.connectome.dataset import load_registered_graph
from service.settings import connectome_directory


@lru_cache(maxsize=1)
def registered_graph():
    return load_registered_graph(connectome_directory())


def outgoing(graph, body_id: int, offset: int, limit: int) -> dict:
    index = int(np.searchsorted(graph.ids, body_id))
    if index >= len(graph.ids) or int(graph.ids[index]) != body_id:
        raise KeyError("Neuron is not in the registered graph")
    first, last = int(graph.ptr[index]), int(graph.ptr[index + 1])
    begin, end = min(first + offset, last), min(first + offset + limit, last)
    sign = int(graph.signs[index])
    return {
        "dataset_id": graph.provenance["dataset_id"],
        "manifest_sha256": graph.provenance["manifest_sha256"],
        "source_id": str(body_id),
        "offset": offset,
        "total": last - first,
        "next_offset": end - first if end < last else None,
        "items": [
            {
                "target_id": str(int(graph.ids[int(graph.posts[i])])),
                "synapse_count": int(graph.counts[i]),
                "model_sign": sign,
            }
            for i in range(begin, end)
        ],
        "limitations": "Sign is derived from predicted transmitter, without receptor context.",
    }


def incoming(graph, body_id: int, offset: int, limit: int) -> dict:
    index = int(np.searchsorted(graph.ids, body_id))
    if index >= len(graph.ids) or int(graph.ids[index]) != body_id:
        raise KeyError("Neuron is not in the registered graph")
    total, selected = 0, []
    for start in range(0, len(graph.posts), 1_000_000):
        block = graph.posts[start : start + 1_000_000]
        matches = np.flatnonzero(block == index) + start
        first, last = max(0, offset - total), min(len(matches), offset + limit - total)
        if first < last:
            selected.extend(int(edge) for edge in matches[first:last])
        total += len(matches)
    source_indices = np.searchsorted(graph.ptr, selected, side="right") - 1
    return {
        "dataset_id": graph.provenance["dataset_id"],
        "manifest_sha256": graph.provenance["manifest_sha256"],
        "target_id": str(body_id),
        "offset": offset,
        "total": total,
        "next_offset": offset + len(selected) if offset + len(selected) < total else None,
        "items": [
            {
                "source_id": str(int(graph.ids[int(source)])),
                "synapse_count": int(graph.counts[edge]),
                "model_sign": int(graph.signs[int(source)]),
            }
            for edge, source in zip(selected, source_indices, strict=True)
        ],
        "limitations": "Sign is derived from predicted transmitter, without receptor context.",
    }
