"""Update four 2026 bibliographic versions from primary registries."""

# ruff: noqa: E501 -- exact record metadata and source locators are intentionally long.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
UPDATES = {
    "S034": {
        "edition": "Neurosurgery 98(4):895-903 (issue 1 April 2026; electronically published 29 August 2025)",
        "locator": "https://pubmed.ncbi.nlm.nih.gov/40879389/",
        "version": "PubMed citation: issue 98(4):895-903 dated 1 April 2026; Epub 29 August 2025",
        "access": "PubMed citation/abstract only; full method remains unavailable",
    },
    "S754": {
        "edition": "Neuromodulation: Technology at the Neural Interface; online ahead of print 23 June 2026, PII S1094-7159(26)00624-0",
        "locator": "https://pubmed.ncbi.nlm.nih.gov/42524811/",
        "version": "PubMed citation: online ahead of print 23 June 2026; no volume, issue or page assignment in checked record",
        "access": "PubMed citation/abstract only; full method remains unavailable",
    },
    "S320": {
        "edition": "Zenodo preprint, version 1.0.0 (21 March 2026)",
        "locator": "https://zenodo.org/api/records/19152238",
        "version": "Zenodo metadata version 1.0.0; publication_date 2026-03-21; related identifier points to author software",
        "access": "Zenodo record and existing archived primary PDF; no journal version established from record relations",
    },
    "S357": {
        "edition": "JPHV (Journal of Pain, Vertigo and Headache) 7(1):37-44",
        "locator": "https://api.crossref.org/works/10.21776%2Fub.jphv.2026.007.01.07",
        "version": "Crossref DOI record: volume 7, issue 1, pages 37-44",
        "access": "Crossref DOI metadata only; publisher full text remains inaccessible",
    },
}


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in records["sources"]}
    for sid, spec in UPDATES.items():
        source = by_id[sid]
        if source["год"] != 2026 or source["издание"] == spec["edition"]:
            raise ValueError(f"{sid} was already rechecked or has changed")
        source["издание"] = spec["edition"]
        source["field_resolution"]["издание"].update({
            "state": "reported", "value": spec["edition"],
            "reason": "Checked against the current primary bibliographic registry; online and issue dates are kept distinct.",
            "checked_at": DATE,
            "locators": [{"url": spec["locator"], "locator": spec["version"]}],
        })
        source["validation"]["notes"] += f" SRC-07 {DATE}: {spec['version']}. {spec['access']}."
        source["field_resolution"]["validation.notes"].update({
            "state": "reported", "value": source["validation"]["notes"],
            "reason": "Dated source-version recheck; access and absence-of-update claims are scoped to checked registries.",
            "checked_at": DATE,
            "locators": [{"url": spec["locator"], "locator": spec["version"]}],
        })
    audit = {
        "meta": {
            "schema_version": "1.0.0",
            "checked_at": DATE,
            "status": "in_progress",
            "scope": "SRC-07 four 2026 source-version rechecks",
            "decision": "four_versions_rechecked_full_2026_corpus_still_open",
        },
        "entries": [
            {
                "source_id": sid,
                "current_version": spec["version"],
                "source_url": spec["locator"],
                "access_boundary": spec["access"],
                "correction_retraction_check": "No update-to relation appeared in the checked Crossref DOI record or correction notice in the checked PubMed/Zenodo record as applicable; absence across all registries is not established.",
                "preprint_journal_relation": "No link established in the checked primary record; S320 is a Zenodo preprint with author software relation, not an independent journal report.",
            }
            for sid, spec in UPDATES.items()
        ],
        "remaining": [
            "Recheck every other 2026 canonical source and preprint-journal link",
            "Later dated correction/retraction refresh",
            "Full text for S034, S754 and S357 if lawfully available",
        ],
    }
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = updated()
    if not args.apply:
        print("Dry run: S034/S754/S320/S357 version metadata; SRC-07 remains open")
        return
    snapshot = snapshot_repository(DATA, label="pre-src07-four-version-recheck")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-version-recheck-audit.json", audit)
    print(f"Rechecked four 2026 records; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
