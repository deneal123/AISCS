"""Validate experimental fragment subset results before publication."""

from __future__ import annotations

import math
import re


class InvalidFragmentPopulationManifest(ValueError):
    pass


def validate_fragment_population_manifest(manifest, *, configuration_sha256, graph_sha256):
    names = {
        "signals.npz",
        "model.json",
        "source-provenance.jsonl",
        "fragment-population-preview.json",
    }
    allowed = names | {"fragment-events.bin", "fragment-response.npz", "fragment-response.bin",
                       "fragment-delta.bin"}
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != "experimental-fragment-population"
        or manifest.get("configuration_sha256") != configuration_sha256
        or manifest.get("graph_sha256") != graph_sha256
        or not all(
            isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (configuration_sha256, graph_sha256)
        )
        or manifest.get("coverage")
        != "explicitly supplied sources only; not a full-network physical recording"
        or not isinstance(manifest.get("files"), list)
        or len(manifest["files"]) not in range(len(names), len(allowed) + 1)
    ):
        raise InvalidFragmentPopulationManifest("fragment_identity")
    seen = set()
    for item in manifest["files"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "bytes", "sha256"}
            or item["name"] not in allowed
            or item["name"] in seen
            or type(item["bytes"]) is not int
            or not 1 <= item["bytes"] <= 256 * 1024 * 1024
            or (item["name"] == "fragment-population-preview.json" and item["bytes"] > 1024 * 1024)
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
        ):
            raise InvalidFragmentPopulationManifest("fragment_files")
        seen.add(item["name"])
    if not names.issubset(seen):
        raise InvalidFragmentPopulationManifest("fragment_files")
    if 'fragment-response.npz' in seen and 'fragment-events.bin' not in seen:
        raise InvalidFragmentPopulationManifest("fragment_files")
    if 'fragment-response.bin' in seen and 'fragment-response.npz' not in seen:
        raise InvalidFragmentPopulationManifest("fragment_files")
    if 'fragment-delta.bin' in seen and 'fragment-response.bin' not in seen:
        raise InvalidFragmentPopulationManifest("fragment_files")


def validate_fragment_population_preview(preview, configuration):
    try:
        simulation = configuration["simulation"]
        duration, dt = simulation["duration_ms"], simulation["dt_ms"]
        samples, shown = preview["samples"], preview["shown_samples"]
        traces = [preview[key] for key in ("time_ms", "neural_uv", "total_uv", "stimulus_fraction")]
        spikes = preview["network_spikes_by_ms"]
        partial = configuration.get("allow_partial_geometry") is True
        unresolved = preview.get("unresolved_graph_pairs")
        limitations = [
            "Расчёт ограничен выбранными клетками.",
            "Фрагменты и граф не имеют обратной связи.",
            "Параметры модели и расположение в теле не откалиброваны.",
            "Положение контактов относительно тканей и формы тела не проверено.",
        ]
        if partial and type(unresolved) is int and unresolved > 0:
            limitations.append(f'Не сопоставлены с отростками синапсы: {unresolved}; '
                               'их события неизвестны и не включены в передачу.')
        if (
            type(duration) not in (int, float)
            or type(dt) not in (int, float)
            or not math.isfinite(duration)
            or not math.isfinite(dt)
            or dt <= 0
            or not 1 <= duration <= 1000
            or not float(duration).is_integer()
            or type(samples) is not int
            or type(preview["stimulus_boundaries_preserved"]) is not bool
            or samples != round(duration / dt) + 1
            or type(shown) is not int
            or not 2 <= shown <= min(samples, 4096)
            or any(not isinstance(trace, list) or len(trace) != shown for trace in traces)
            or any(
                type(v) not in (int, float) or not math.isfinite(v)
                for trace in traces
                for v in trace
            )
            or not math.isclose(traces[0][0], 0, abs_tol=1e-8)
            or not math.isclose(traces[0][-1], duration, abs_tol=1e-8, rel_tol=0)
            or any(a >= b for a, b in zip(traces[0], traces[0][1:], strict=False))
            or any(abs(v) > 1.0 + 1e-9 for v in traces[3])
            or not isinstance(spikes, list)
            or len(spikes) != int(duration) + 1
            or any(type(value) is not int or value < 0 for value in spikes)
            or spikes[0] != 0
            or type(preview["source_cells"]) is not int
            or preview["source_cells"] != len(configuration["source_ids"])
            or type(preview["edge_event_count"]) is not int
            or preview["edge_event_count"] < 0
            or preview["units"] != {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"}
            or (partial and (type(unresolved) is not int or unresolved < 0))
            or (not partial and 'unresolved_graph_pairs' in preview)
            or preview["limitations"] != limitations
        ):
            raise InvalidFragmentPopulationManifest("fragment_preview")
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidFragmentPopulationManifest("fragment_preview") from exc
