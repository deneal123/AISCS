"""Correct S282 full-text status and document its primary abstract access."""

# ruff: noqa: E501 -- retain exact service URLs and access results.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
CORE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID%3APPR1093728&format=json&resultType=core"
JATS = "https://www.ebi.ac.uk/europepmc/webservices/rest/PPR1093728/fullTextXML"
PDF = "https://europepmc.org/api/fulltextRepo?pprId=PPR1093728&type=FILE&fileName=EMS209354-pdf.pdf&mimeType=application/pdf"


def resolve(source: dict, path: str, value: object, locator: str) -> None:
    source["field_resolution"][path] = {
        "state": "reported",
        "value": value,
        "reason": "Primary preprint abstract indexed by Europe PMC; full methods remain inaccessible in this environment.",
        "checked_at": DATE,
        "locators": [{"url": CORE, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S282")
    if source["validation"]["full_text_status"] != "checked":
        raise ValueError("S282 full-text status changed; review manually")
    source["validation"].update({
        "status": "partially_verified",
        "full_text_status": "metadata_only",
        "checked_at": DATE,
        "notes": "Primary abstract verifies larval Drosophila, connectomic, imaging, neural-manipulation and rolling endpoints. Exact stimulus protocol, cohorts and neural measurements cannot be extracted: bioRxiv PDF returned HTTP 429, Europe PMC PDF HTTP 403 and Europe PMC fullTextXML HTTP 500 on 2026-09-24.",
    })
    source["evidence"].update({
        "population": "Drosophila larvae; cohort counts unavailable from accessible abstract",
        "subject_domain": "drosophila_larva",
        "modalities": ["connectome", "neural_activity", "behavior"],
        "target_label": "rolling escape behavior, with exact experimental readouts unavailable",
    })
    for path, value, locator in (
        ("evidence.population", source["evidence"]["population"], "Primary abstract, organism and methods sentence"),
        ("evidence.subject_domain", "drosophila_larva", "Primary abstract, Drosophila larva"),
        ("evidence.modalities", source["evidence"]["modalities"], "Primary abstract, connectomic analyses, imaging, neural manipulation and behavior"),
        ("evidence.target_label", source["evidence"]["target_label"], "Primary abstract, rolling escape endpoint"),
        ("validation.checked_at", DATE, "Primary abstract and access endpoints checked on 2026-09-24"),
        ("validation.notes", source["validation"]["notes"], "Primary abstract and Europe PMC full-text links"),
    ):
        resolve(source, path, value, locator)
    remaining = next(item for item in audit["meta"]["remaining_primary_access"] if item["source_id"] == "S282")
    remaining.update({
        "checked_at": DATE,
        "result": "Primary abstract available through Europe PMC core, but exact methods unavailable. bioRxiv PDF HTTP 429; Europe PMC listed PDF HTTP 403; Europe PMC JATS fullTextXML HTTP 500.",
        "next": "Retrieve the primary full text from a working author/publisher deposit; do not infer exact stimuli or cohort sizes from the abstract.",
        "alternate_primary_endpoints": [
            {"url": CORE, "result": "primary abstract available; no full methods"},
            {"url": PDF, "result": "listed open-access PDF; HTTP 403 in current environment"},
            {"url": JATS, "result": "fullTextXML HTTP 500 in current environment"},
        ],
    })
    report = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    report.update(completeness_summary(records["sources"]))
    return records, audit, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit, report = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s282-abstract-access-correction")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-nociception-audit.json", audit)
        atomic_write_json(DATA / "completeness-report.json", report)
        print(f"Applied S282 access correction; snapshot: {snapshot}")
    else:
        print("Dry run: S282 abstract verified, exact methods remain inaccessible")


if __name__ == "__main__":
    main()
