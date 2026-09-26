"""Upgrade S320 from metadata-only to checked primary Zenodo full text."""

# ruff: noqa: E501 -- preserve precise primary text and page locators.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
PDF = "https://zenodo.org/api/records/19152238/files/paper_emergent_individuality.pdf/content"
RECORD = "https://zenodo.org/records/19152238"
PDF_SHA256 = "3C3FDEC049B5D9E811FC99E7942542B22A55634274B38C1E1066EABDEF3607C2"


def field(state: str, value: str | None, locator: str, reason: str) -> dict:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": PDF, "locator": locator}],
    }


def measured(value: str, locator: str) -> dict:
    return field("reported", value, locator, "Directly reported by the author preprint; numerical results have not been independently reproduced.")


def resolution(source: dict, path: str, value: object, locator: str) -> None:
    source["field_resolution"][path] = {
        "state": "reported",
        "value": value,
        "reason": "Read in the author-deposited full text; source claims are not independent biological validation.",
        "checked_at": DATE,
        "locators": [{"url": PDF, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S320")
    if source["validation"]["full_text_status"] != "metadata_only":
        raise ValueError("S320 no longer metadata-only")
    if any(item["source_id"] == "S320" for item in audit["entries"]):
        raise ValueError("S320 already audited")

    source["identifiers"]["exact_url"] = RECORD
    source["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": "Two simulated agents based on one adult female FlyWire brain",
        "subject_domain": "simulation",
        "modalities": ["connectome", "neural_activity", "movement_pose", "behavior", "simulation_state"],
        "sample_size": 2,
        "access_status": "open",
    })
    source["метод"] = "FlyWire v783, 138,639-neuron LIF simulation, Hebbian plasticity and NeuroMechFly v2 embodiment"
    source["датасет"] = "FlyWire FAFB v783; two simulated agents"
    source["производительность"] = "Author-reported simulation: escape mode 81% versus 47%; composite integration proxy 0.221 versus 0.198 across eight paired sessions"
    source["ограничения"] = (
        "Author-deposited preprint and simulated agents only. No new matched biological neural or behavioral comparator, "
        "independent replication or pain endpoint. Composite integration index is an engineered proxy and the paper "
        "explicitly states it is not evidence of subjective experience."
    )
    source["validation"].update({
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "synthetic_individual",
        "cross_subject": "no",
        "external_validation": "no",
        "notes": "Primary Zenodo PDF inspected; model and author-reported outcomes extracted. Two simulated agents share the same female-brain connectome; no animal-level validation or independent reproduction is shown.",
    })
    values = {
        "identifiers.exact_url": (RECORD, "Zenodo record 19152238, Files"),
        "evidence.species": (source["evidence"]["species"], "PDF p. 1 Abstract; p. 2 Introduction and Methods 2.1"),
        "evidence.population": (source["evidence"]["population"], "PDF pp. 1-3, Abstract, Introduction and Methods 2.5"),
        "evidence.subject_domain": ("simulation", "PDF pp. 1-3, Methods 2.1-2.5"),
        "evidence.modalities": (source["evidence"]["modalities"], "PDF pp. 2-3, Methods 2.1-2.5"),
        "evidence.sample_size": (2, "PDF p. 3, Methods 2.5: two instances, eight paired sessions"),
        "evidence.access_status": ("open", "Zenodo record 19152238, Files: publicly downloadable author PDF"),
        "метод": (source["метод"], "PDF p. 2, Methods 2.1-2.3"),
        "датасет": (source["датасет"], "PDF p. 2, Methods 2.1"),
        "производительность": (source["производительность"], "PDF pp. 1, 5-8, Abstract and Results 3.1-3.4"),
        "ограничения": (source["ограничения"], "PDF pp. 8-10, Discussion 4.4 and Conclusion"),
        "validation.checked_at": (DATE, "Full-text inspection on 2026-09-24"),
        "validation.split_unit": ("synthetic_individual", "PDF p. 3, Methods 2.5"),
        "validation.cross_subject": ("no", "PDF p. 3, Methods 2.5: two synthetic agents"),
        "validation.external_validation": ("no", "PDF pp. 3-10, Methods, Results and Limitations"),
        "validation.notes": (source["validation"]["notes"], "PDF pp. 1-10, Methods, Results and Limitations"),
    }
    for path, (value, page) in values.items():
        resolution(source, path, value, page)
    audit["entries"].append({
        "source_id": "S320",
        "extraction": {
            "connectome_version": measured("FlyWire FAFB v783; 138,639 modeled neurons and 15,091,983 signed weighted edges", "PDF pp. 1-2, Abstract and Methods 2.1"),
            "organism_sex_stage": measured("Drosophila melanogaster; one adult female brain connectome copied into two simulated agents", "PDF pp. 1-3, Abstract, Introduction and Methods 2.5"),
            "dynamic_model": measured("Whole-brain 5 kHz LIF network with alpha-function synapses, global Hebbian weight updates and NeuroMechFly v2/MuJoCo sensorimotor loop", "PDF pp. 2-3, Methods 2.1-2.5"),
            "experimental_comparator": field("not_applicable", None, "PDF pp. 3-10, simulation protocol, Results and Limitations", "Two simulated agents are compared with each other; no matched new biological neural recording or fly-behavior experiment is reported."),
            "scope_boundary": measured("Author-reported simulation differences and engineered neural-integration proxies; no subjective consciousness/pain evidence, human ECAP or SCS endpoint", "PDF pp. 8-10, Discussion 4.3-4.4 and Conclusion"),
        },
        "primary_pdf_sha256": PDF_SHA256,
        "evidence_limit": "Full text establishes what the authors report, not independent reproduction or biological validation.",
    })
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    report = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    report.update(completeness_summary(records["sources"]))
    return records, audit, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit, report = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s320-full-text-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        atomic_write_json(DATA / "completeness-report.json", report)
        print(f"Applied S320 full-text review; snapshot: {snapshot}")
    else:
        print("Dry run: S320 primary PDF checked, connectome audit has 11 entries")


if __name__ == "__main__":
    main()
