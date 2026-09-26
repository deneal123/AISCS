"""Clarify S106 FAFB alignment and specimen provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
FLYWIRE = "https://pmc.ncbi.nlm.nih.gov/articles/PMC8903166/"
FAFB = "https://pmc.ncbi.nlm.nih.gov/articles/PMC6063995/"


def locator(url: str, section: str) -> dict:
    return {"url": url, "locator": section}


def revised() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S106")
    entry = next(item for item in audit["entries"] if item["source_id"] == "S106")
    version = entry["extraction"]["connectome_version"]
    if version["state"] != "not_reported":
        raise ValueError("S106 frozen connectome version is no longer not_reported")
    version["reason"] = (
        "FlyWire Methods identify the published FAFB EM alignment v14 and FlyWire image "
        "alignment v14.1. Neither identifies a frozen release of the proofread "
        "connectivity graph analyzed in this platform paper."
    )
    version["locators"] = [locator(FLYWIRE, "Methods > Alignment and Cross alignment registration")]
    sex = entry["extraction"]["organism_sex_stage"]
    if sex["value"] != "Drosophila melanogaster; female; adult brain":
        raise ValueError("Unexpected S106 specimen description")
    sex["reason"] = (
        "The FlyWire paper uses FAFB; the original FAFB specimen paper identifies the adult female."
    )
    sex["locators"] = [
        locator(FLYWIRE, "Introduction: reused FAFB adult-brain EM volume"),
        locator(
            FAFB,
            "STAR Methods > Experimental Model and Subject Details",
        ),
    ]
    for key, item in source["field_resolution"].items():
        if key == "evidence.population" or str(item.get("value") or "").startswith(
            "FAFB adult female brain EM volume"
        ):
            item["reason"] = (
                "Female adult specimen identified in the original FAFB study cited by FlyWire."
            )
            item["locators"] = [
                locator(FLYWIRE, "Introduction: reused FAFB adult-brain EM volume"),
                locator(FAFB, "STAR Methods > Experimental Model and Subject Details"),
            ]
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = revised()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s106-fafb-provenance-correction")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        print(f"Corrected S106 provenance; snapshot: {snapshot}")
    else:
        print("Dry run: S106 provenance correction ready")


if __name__ == "__main__":
    main()
