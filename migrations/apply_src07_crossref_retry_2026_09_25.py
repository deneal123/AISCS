"""Apply reviewed bibliographic retry results and medRxiv S330 version evidence."""

# ruff: noqa: E501 -- preserve explicit primary metadata locators and version caveats.

import argparse
import html
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
MEDRXIV = "https://api.medrxiv.org/details/medrxiv/10.1101/2025.09.22.25336341"
APPROVED_EDITION_IDS = {
    "S004", "S005", "S007", "S040", "S069", "S078", "S082", "S088", "S162", "S249", "S279",
}


def edition(row: dict) -> str:
    title = html.unescape(row["container_title"])
    if row.get("volume"):
        title += f" {row['volume']}"
    if row.get("issue"):
        title += f"({row['issue']})"
    page = row.get("page") or row.get("article_number")
    if page:
        title += f":{page}"
    return title


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "src07-crossref-retry-2026-09-25.json").read_text(encoding="utf-8"))
    by_id = {source["id"]: source for source in records["sources"]}
    rows = {row["source_id"]: row for row in audit["rows"]}
    changes = []
    for sid in sorted(APPROVED_EDITION_IDS, key=lambda value: int(value[1:])):
        source, row = by_id[sid], rows[sid]
        if row["status"] != "crossref_resolved" or row["registry_doi"].lower() != source["identifiers"]["doi"].lower():
            raise ValueError(f"Unresolved or mismatched DOI: {sid}")
        old, new = source["издание"], edition(row)
        if old == new:
            continue
        source["издание"] = new
        source["field_resolution"]["издание"].update({
            "state": "reported", "value": new,
            "reason": "Publisher DOI registration supplies this volume, issue and page/article number; bibliographic correction only.",
            "checked_at": DATE,
            "locators": [{"url": row["query_url"], "locator": "message.container-title, volume, issue, page, article-number"}],
        })
        changes.append({"source_id": sid, "old_edition": old, "new_edition": new, "url": row["query_url"]})

    source = by_id["S330"]
    if source["название"] != "Towards Personalized Edge-AI for Medicine: Efficient Neuromorphic Frameworks for Seizure Detection and Prediction":
        raise ValueError("S330 current title differs from medRxiv version 2")
    old = source["издание"]
    new = "medRxiv preprint v2 (18 August 2026)"
    source["издание"] = new
    source["field_resolution"]["издание"].update({
        "state": "reported", "value": new,
        "reason": "The official medRxiv version collection identifies v1 (2025-09-25, older title) and v2 (2026-08-18, current card title) under the same DOI. The Crossref first-posting date is not the v2 date.",
        "checked_at": DATE,
        "locators": [{"url": MEDRXIV, "locator": "collection[0].version/date/title and collection[1].version/date/title"}],
    })
    changes.append({"source_id": "S330", "old_edition": old, "new_edition": new, "url": MEDRXIV})
    audit["reviewed_edition_updates"] = changes
    audit["manual_review_flags"] = [
        {
            "source_id": "S162", "status": "known_publisher_correction",
            "correction_doi": "10.1007/s40122-026-00838-7",
            "boundary": "Springer correction replaces 'Standard Method' with 'Artefact Model Method'; S162 method and limitations already record this. This is not an independent study.",
            "locators": [
                {"url": rows["S162"]["query_url"], "locator": "message.updated-by[0]"},
                {"url": "https://link.springer.com/article/10.1007/s40122-026-00838-7", "locator": "Correction paragraph and Change history"},
            ],
        },
        {
            "source_id": "S330", "status": "two_versions_same_doi",
            "boundary": "Crossref published=2025-09-25 refers to first posting; medRxiv v2 dated 2026-08-18 has the current canonical title. Do not deduplicate as separate studies.",
            "locators": [{"url": MEDRXIV, "locator": "collection[0] and collection[1]"}],
        },
        {
            "source_id": "S148", "status": "edition_not_applied",
            "boundary": "Crossref page=1-18 and volume='Volume 19' do not reconcile with Europe PMC article identifier 617733; retaining existing generic edition pending publisher check.",
            "locators": [{"url": rows["S148"]["query_url"], "locator": "message.volume and page"}],
        },
    ]
    audit["meta"]["reviewed_edition_updates"] = len(changes)
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = updated()
    if not args.apply:
        print(f"Dry run: {len(audit['reviewed_edition_updates'])} edition/version changes")
        return
    snapshot = snapshot_repository(DATA, label="pre-src07-crossref-retry-editions")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-crossref-retry-2026-09-25.json", audit)
    print(f"Updated {len(audit['reviewed_edition_updates'])} editions; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
