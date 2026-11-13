"""Replay a trusted saved MaleCNS run on all incoming edges of one SWC cell.

This isolated, one-way engineering calculation does not validate physiology,
recover missing anatomy, or update the original network state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.dataset import load_registered_graph  # noqa: E402
from service.infrastructure.connectome.synapse_index import SynapseBatchIndex  # noqa: E402
from service.infrastructure.stimulation.recording.replay_export import (
    export_reference_replay,  # noqa: E402
)
from service.infrastructure.stimulation.synaptic_replay import (
    execute_all_incoming_replay,  # noqa: E402
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--synapses", type=Path, required=True)
    parser.add_argument("--synapse-index", type=Path, required=True)
    parser.add_argument("--source-md5", required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--connectome-bin", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Output directory must be empty")
    run = json.loads(args.run_json.read_text(encoding="utf-8"))
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    if run.get("state") != "completed":
        raise ValueError("Input run is not completed")
    description = run["result"]["preview"]["connectome"]
    matching = [item for item in run["result"]["manifest"]["files"]
                if item.get("name") == "connectome.bin"]
    if len(matching) != 1:
        raise ValueError("Run manifest must identify one connectome buffer")
    binary = args.connectome_bin.read_bytes()
    if type(matching[0].get("bytes")) is not int or matching[0]["bytes"] != len(binary):
        raise ValueError("Connectome buffer size does not match run manifest")
    index = SynapseBatchIndex(args.synapses, args.ids, args.synapse_index, args.source_md5)
    graph = load_registered_graph(args.graph)
    result = execute_all_incoming_replay(
        index, graph, settings["body_id"], args.morphology_dir,
        binary=binary, description=description, expected_sha256=matching[0]["sha256"],
        schedule_parameters=settings["schedule"], simulation_parameters=settings["simulation"],
        electrode_um=settings["electrode_um"], reference_um=settings["reference_um"],
        source_model=settings.get("source_model", "pointsource"),
        progress=lambda n, offset, next_offset: print(
            f"page={n} offset={offset} next={next_offset}", file=sys.stderr, flush=True
        ),
    )
    manifest = export_reference_replay(result, args.output)
    print(json.dumps({"body_id": result["mapping"]["body_id"],
                      "pages": result["mapping"]["pages"],
                      "events": len(result["replay"]["events"]), "files": manifest["files"],
                      "interpretation": manifest["interpretation"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
