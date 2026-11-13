"""Bounded deterministic preview of verified experimental fragment signals."""

from __future__ import annotations

import numpy as np


def fragment_population_preview(arrays, *, source_count, duration_ms, edge_event_count,
                                unresolved_graph_pairs=None):
    """Retain per-bin extrema; values are a subset of actual computed samples."""
    time = arrays["time_ms"]
    if (
        type(source_count) is not int
        or source_count < 1
        or type(duration_ms) is not int
        or duration_ms < 1
        or type(edge_event_count) is not int
        or edge_event_count < 0
        or (unresolved_graph_pairs is not None
            and (type(unresolved_graph_pairs) is not int or unresolved_graph_pairs < 0))
    ):
        raise ValueError("Invalid fragment preview metadata")
    traces = [arrays[name] for name in ("neural_uv", "total_uv", "stimulus_fraction")]
    stimulus = arrays["stimulus_fraction"]
    active = np.abs(stimulus) > 1e-9
    transition = np.flatnonzero(active[1:] != active[:-1])
    slopes = np.diff(stimulus) / np.diff(time)
    changes = np.flatnonzero(~np.isclose(slopes[1:], slopes[:-1], rtol=1e-6, atol=1e-9)) + 1
    protected = np.unique(np.concatenate((transition, transition + 1, changes)))
    preserve_boundaries = len(protected) <= 2048
    if not preserve_boundaries:
        protected = np.empty(0, dtype=int)
    max_bins = (4096 - len(protected)) // 8
    edges = np.linspace(0, len(time), min(400, len(time), max_bins) + 1, dtype=int)
    selected = set(int(index) for index in protected)
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        selected.update((int(start), int(end - 1)))
        for signal in traces:
            selected.add(int(start + np.argmin(signal[start:end])))
            selected.add(int(start + np.argmax(signal[start:end])))
    positions = np.asarray(sorted(selected), dtype=int)
    ticks = arrays["spike_times_ms"]
    if np.any(ticks != np.rint(ticks)):
        raise ValueError("Network event times are not integer ticks")
    counts = np.bincount(ticks.astype(int), minlength=duration_ms + 1)
    result = {
        "samples": len(time),
        "shown_samples": len(positions),
        "stimulus_boundaries_preserved": preserve_boundaries,
        "time_ms": time[positions].tolist(),
        "neural_uv": traces[0][positions].tolist(),
        "total_uv": traces[1][positions].tolist(),
        "stimulus_fraction": traces[2][positions].tolist(),
        "network_spikes_by_ms": counts.tolist(),
        "source_cells": source_count,
        "edge_event_count": edge_event_count,
        "units": {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"},
        "limitations": [
            "Расчёт ограничен выбранными клетками.",
            "Фрагменты и граф не имеют обратной связи.",
            "Параметры модели и расположение в теле не откалиброваны.",
            "Положение контактов относительно тканей и формы тела не проверено.",
        ],
    }
    if unresolved_graph_pairs is not None:
        result['unresolved_graph_pairs'] = unresolved_graph_pairs
        if unresolved_graph_pairs:
            result['limitations'].append(
                f'Не сопоставлены с отростками синапсы: {unresolved_graph_pairs}; '
                'их события неизвестны и не включены в передачу.')
    return result
