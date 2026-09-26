"""Synchronize the NS-03 coverage note with the completed primary audits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def revised_protocol() -> dict:
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-03")
    entries = {item["source_id"]: item for item in audit["entries"]}
    if set(stream["source_ids"]) != set(entries):
        raise ValueError("NS-03 source list and nociception audit differ")
    required = {"stimulus", "neural_response", "behavior", "pain_boundary"}
    if any(not required <= set(item["extraction"]) for item in entries.values()):
        raise ValueError("An NS-03 candidate lacks required extraction")
    if "S212 and S282 await primary full text" not in stream["coverage_note"]:
        raise ValueError("Expected stale NS-03 coverage note not found")
    stream["coverage_note"] = (
        "Seventeen canonical candidates include original experiments, protocols, a dataset "
        "description and reviews; their evidence roles are screened separately. All 17 have "
        "source-specific stimulus, neural-response, behavior and pain-boundary extraction. "
        "S212 was checked against primary JATS and S282 against the author preprint PDF. "
        "Backward and forward citation screening remains open."
    )
    return protocol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol = revised_protocol()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns03-coverage-note-correction")
        atomic_write_json(DATA / "search-protocol.json", protocol)
        print(f"Corrected NS-03 coverage note; snapshot: {snapshot}")
    else:
        print("Dry run: NS-03 coverage note correction ready")


if __name__ == "__main__":
    main()
