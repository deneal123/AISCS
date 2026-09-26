"""Link S227's arXiv manuscript to its verified WACV 2026 proceedings record."""

# ruff: noqa: E501 -- exact bibliographic URLs and identity boundary are intentional.

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
ARXIV = "https://arxiv.org/abs/2508.12522"
CROSSREF = "https://api.crossref.org/works/10.1109%2FWACV61042.2026.00352"
CONFERENCE = "https://wacv.thecvf.com/Conferences/2026/AcceptedPapers"


def updated() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S227")
    if source["identifiers"]["doi"] is not None or source["identifiers"]["arxiv_id"] != "2508.12522":
        raise ValueError("S227 identifiers differ from the reviewed starting state")
    edition = "2026 IEEE/CVF Winter Conference on Applications of Computer Vision (WACV):3606-3616"
    source["издание"] = edition
    source["identifiers"]["doi"] = "10.1109/WACV61042.2026.00352"
    source["field_resolution"]["издание"].update({
        "state": "reported", "value": edition,
        "reason": "IEEE DOI registration identifies the WACV 2026 proceedings article and pages; arXiv labels the same title WACV 2026. One canonical study retains both identifiers.",
        "checked_at": DATE,
        "locators": [
            {"url": CROSSREF, "locator": "message.title, type, container-title, page, published"},
            {"url": ARXIV, "locator": "Comments: WACV 2026; submission history v1/v2"},
        ],
    })
    source["field_resolution"]["identifiers.doi"].update({
        "state": "reported", "value": source["identifiers"]["doi"],
        "reason": "Proceedings DOI is registered to the same exact title and author group; the arXiv record states WACV 2026. A formal Crossref relation to the arXiv DOI is not asserted.",
        "checked_at": DATE,
        "locators": [
            {"url": CROSSREF, "locator": "message.DOI, title, author, relation"},
            {"url": CONFERENCE, "locator": "Accepted Papers: MuSACo title and author list"},
        ],
    })
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE, "source_id": "S227", "status": "proceedings_version_verified"},
        "proceedings_doi": source["identifiers"]["doi"],
        "edition": edition,
        "arxiv_id": "2508.12522",
        "arxiv_versions": [
            {"version": "v1", "date": "2025-08-17"},
            {"version": "v2", "date": "2025-12-08"},
        ],
        "locators": [
            {"url": CROSSREF, "locator": "message.DOI, title, author, container-title, page, published, relation"},
            {"url": ARXIV, "locator": "title, authors, WACV 2026 comment, submission history"},
            {"url": CONFERENCE, "locator": "Accepted Papers: matching title and authors"},
        ],
        "identity_boundary": "Exact title and authors plus arXiv WACV comment support one study with preprint and proceedings versions. Crossref relation is empty, so this is a curated bibliographic identity, not a registered Crossref preprint-journal relation.",
        "scientific_boundary": "BioVid/StressID expression adaptation is not patient-linked SCS outcome prediction or a human ECAP transfer validation.",
    }
    return records, completeness, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, completeness, audit = updated()
    if not args.apply:
        print("Dry run: S227 WACV 2026 DOI and arXiv version linked")
        return
    snapshot = snapshot_repository(DATA, label="pre-s227-wacv-version")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "completeness-report.json", completeness)
    atomic_write_json(DATA / "src07-s227-wacv-recheck-2026-09-25.json", audit)
    print(f"Updated S227; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
