"""Resolve generic source-identity matrix locators to official records."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S044": (
        "https://pubmed.ncbi.nlm.nih.gov/42600964/",
        "PubMed citation: title, authors, Journal of Pain 49:106416, "
        "DOI 10.1016/j.jpain.2026.106416, PMID 42600964.",
    ),
    "S040": (
        "https://api.crossref.org/works/10.1016%2Fj.inffus.2026.104173",
        "Crossref message.DOI, title and type: GIAFormer; journal article.",
    ),
    "S079": (
        "https://pubmed.ncbi.nlm.nih.gov/41504676/",
        "PubMed citation: DOI 10.1016/j.neurom.2025.11.011 "
        "and Neuromodulation 2026;29(6):913-920.",
    ),
    "S082": (
        "https://api.crossref.org/works/10.1016%2Fj.bspc.2026.109815",
        "Crossref message.DOI, title and type: hybrid CNN-BiLSTM "
        "pain-intensity classification; journal article.",
    ),
    "S086": (
        "https://api.crossref.org/works/10.1109%2FFG67764.2026.11556963",
        "Crossref message.DOI, title and type: hierarchical "
        "cross-attention pain-classification paper; proceedings article.",
    ),
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    for source_id, (url, locator) in LOCATORS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["claim"] == "The bibliographic source exists under the verified identifier."
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic identity row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "five_identity_locators_reviewed",
        "boundary": "Official citation/DOI metadata establishes source identity only. "
        "It is not evidence for clinical validation or source-specific methods.",
    }
    snapshot = snapshot_repository(DATA, label="pre-five-identity-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "five-identity-locator-review-2026-09-25.json", audit)
    print(f"Updated five identity locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
