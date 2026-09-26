"""Pin S782's FAFB source after checking the primary full-text Methods."""

# ruff: noqa: E501 -- preserve exact source distinctions and locators.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13314972/fullTextXML"
DATE = "2026-09-25"
DATASET = "Female adult fly brain (FAFB) FlyWire materialization snapshot 783 for the grooming network; MANC v1.2.1 is used only for supplementary VNC figures. Optogenetically stimulated head/antenna kinematics came from 10 female adult training flies."


def updated() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S782")
    if "grooming-circuit connectome" not in source["датасет"]:
        raise ValueError("S782 source changed")
    source["датасет"] = DATASET
    source["evidence"]["population"] = "Female adult FAFB FlyWire snapshot 783 and separate female adult flies in optogenetic grooming experiments"
    source["validation"]["notes"] += " Methods > Connectome analysis identifies FAFB FlyWire snapshot 783 for the brain network and MANC v1.2.1 only for supplementary VNC figures; Methods > Fly stocks identifies female adult experimental flies."
    for key in ("датасет", "evidence.population", "validation.notes"):
        value = {"датасет": source["датасет"], "evidence.population": source["evidence"]["population"], "validation.notes": source["validation"]["notes"]}[key]
        source["field_resolution"][key].update({
            "state": "reported", "value": value,
            "reason": "Primary Methods distinguish the FAFB graph snapshot from supplementary MANC and identify female adult experimental flies.",
            "checked_at": DATE,
            "locators": [{"url": URL, "locator": "Methods > Connectome analysis: FlyWire materialization snapshot 783 and MANC v1.2.1; Methods > Fly stocks"}],
        })
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    extraction = next(item["extraction"] for item in audit["entries"] if item["source_id"] == "S782")
    extraction["connectome_version"].update({
        "state": "reported",
        "value": "FAFB FlyWire materialization snapshot 783 for adult female brain connectivity; MANC v1.2.1 for separate supplementary VNC figures",
        "reason": "The primary Methods explicitly assign these two versions to distinct analyses. Neither identifies the source matrix used by S740.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": "Methods > Connectome analysis, first paragraph; Supplementary Figure 7G-H"}],
    })
    extraction["organism_sex_stage"].update({
        "value": "Drosophila melanogaster; female adult FAFB graph and female adult experimental flies",
        "reason": "Primary Methods identify female adult graph and female adult experimental flies.",
        "locators": [{"url": URL, "locator": "Methods > Connectome analysis; Methods > Fly stocks"}],
    })
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    row = next(item for item in matrix["rows"] if item["batch_id"] == "ns04-model-perturbation-primary-2026-09-25")
    row["verified_evidence"] += " S782 Methods > Connectome analysis pins FAFB FlyWire materialization snapshot 783 and distinguishes supplementary MANC v1.2.1."
    row["limitations"] = row["limitations"].replace("Exact graph releases remain unresolved in checked texts.", "S782 pins its FAFB snapshot; S783's immutable FlyWire model-graph release is unresolved in the checked text. These versions do not determine the S740 matrix releases.")
    return records, audit, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = updated()
    if not args.apply:
        print("Dry run: correct S782 FAFB snapshot 783 and female adult cohort")
        return
    snapshot = snapshot_repository(DATA, label="pre-s782-fafb-snapshot-correction")
    for name, payload in zip(("records.json", "drosophila-connectome-audit.json", "evidence-matrix.json"), outputs, strict=True):
        atomic_write_json(DATA / name, payload)
    print(f"Corrected S782; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
