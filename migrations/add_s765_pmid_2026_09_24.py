"""Add the PubMed identifier independently checked after S765 publication."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://pubmed.ncbi.nlm.nih.gov/36937564/"


def main() -> None:
    path = DATA / "records.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in data["sources"] if item["id"] == "S765")
    if record["identifiers"]["pmid"] is not None:
        raise ValueError("S765 PMID already populated; inspect before rerun")
    record["identifiers"]["pmid"] = "36937564"
    record["field_resolution"]["identifiers.pmid"] = {
        "state": "reported",
        "value": "36937564",
        "reason": "PubMed identifies the publisher DOI and the article with PMID 36937564.",
        "checked_at": "2026-09-24",
        "locators": [{"url": URL, "locator": "Citation header; PMID, PMCID and DOI"}],
    }
    snapshot = snapshot_repository(DATA, label="pre-s765-pmid-correction")
    atomic_write_json(path, data)
    print(f"Updated S765 PMID; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
