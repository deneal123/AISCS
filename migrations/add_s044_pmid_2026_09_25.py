"""Add the directly verified PubMed identifier to S044."""

import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://pubmed.ncbi.nlm.nih.gov/42600964/"


def main() -> None:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S044")
    if source["identifiers"]["pmid"] not in (None, "42600964"):
        raise ValueError("S044 PMID has a conflicting value")
    if any(
        item["id"] != "S044" and item["identifiers"]["pmid"] == "42600964"
        for item in records["sources"]
    ):
        raise ValueError("PMID already belongs to another source")
    source["identifiers"]["pmid"] = "42600964"
    source["field_resolution"]["identifiers.pmid"] = {
        "state": "reported",
        "value": "42600964",
        "reason": "The official PubMed citation lists this PMID and the source DOI.",
        "checked_at": "2026-09-25",
        "locators": [
            {
                "url": URL,
                "locator": "Citation, PMID 42600964 and DOI 10.1016/j.jpain.2026.106416",
            }
        ],
    }
    completeness = json.loads(
        (DATA / "completeness-report.json").read_text(encoding="utf-8")
    )
    completeness.update(completeness_summary(records["sources"]))
    snapshot = snapshot_repository(DATA, label="pre-s044-pmid-completeness")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "completeness-report.json", completeness)
    print(f"Added S044 PMID; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
