"""Independently audit a self-contained isolated-cell replay export."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.stimulation.recording.replay_export import (  # noqa: E402
    load_verified_reference_replay,
)


def audit(directory):
    data = load_verified_reference_replay(directory)
    evidence = data["evidence"]
    mapping, spikes = evidence["mapping"], evidence["selected_spikes"]
    replay, config = evidence["replay"], evidence["provenance"]["configuration"]
    events, sources = replay["events"], replay["event_sources"]
    if (mapping.get("direction") != "incoming" or len(events) != len(sources)
            or events != config.get("synaptic_events")):
        raise ValueError("Replay event journal and solution configuration differ")
    seen, delays = set(), []
    for event, source in zip(events, sources, strict=True):
        candidate_index, spike_index = source["candidate_index"], source["spike_index"]
        if (type(candidate_index) is not int
                or not 0 <= candidate_index < len(mapping["candidates"])
                or type(spike_index) is not int or spike_index < 0):
            raise ValueError("Invalid event source index")
        candidate = mapping["candidates"][candidate_index]
        body = candidate["partner_id"]
        if body not in spikes or spike_index >= len(spikes[body]):
            raise ValueError("Missing source spike")
        time = spikes[body][spike_index]
        key = (candidate_index, spike_index)
        if (key in seen or source["presynaptic_id"] != body
                or source["spike_time_ms"] != time
                or event["child_node_id"] != candidate["child_node_id"]
                or event["position"] != candidate["segment_fraction"]):
            raise ValueError("Event provenance does not match source")
        delay = event["time_ms"] - time
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Invalid event delay")
        seen.add(key)
        delays.append(delay)
    if delays and any(not math.isclose(delay, delays[0], rel_tol=1e-12, abs_tol=1e-12)
                      for delay in delays):
        raise ValueError("Inconsistent event delays")
    if delays:
        expected = {(i, j) for i, candidate in enumerate(mapping["candidates"])
                    for j, time in enumerate(spikes[candidate["partner_id"]])
                    if time + delays[0] < config["duration_ms"]}
        if expected != seen:
            raise ValueError("Replay omits or duplicates in-window events")
    return {"body_id": mapping["body_id"], "events": len(events),
            "candidates": len(mapping["candidates"]), "delay_ms": delays[0] if delays else None,
            "event_coverage_checked": bool(delays),
            "edge_coverage": mapping.get("complete_graph_edge_coverage", False),
            "samples": len(data["traces"]["time_ms"]),
            "interpretation": "self-consistency only; no physiological validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
