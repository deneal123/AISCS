"""Apply reviewed 2026 edition details from the dated Crossref sweep."""

# ruff: noqa: E501 -- preserve exact registry field locators and bounded claims.

import argparse
import html
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
APPROVED_IDS = {
    "S008", "S015", "S022", "S025", "S044", "S045", "S066",
    "S075", "S084", "S086", "S097", "S138", "S164", "S273",
    "S285", "S360", "S363", "S738", "S748",
}


def edition(row: dict) -> str:
    title = html.unescape(row["container_title"])
    volume = row.get("volume")
    issue = row.get("issue")
    page = row.get("page") or row.get("article_number")
    if volume:
        title += f" {volume}"
    if issue:
        title += f"({issue})"
    if page:
        title += f":{page}"
    return title


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    sweep = json.loads((DATA / "src07-crossref-sweep-2026-09-25.json").read_text(encoding="utf-8"))
    by_id = {source["id"]: source for source in records["sources"]}
    rows = {row["source_id"]: row for row in sweep["rows"]}
    if not all(sid in by_id and rows[sid]["status"] == "crossref_resolved" for sid in APPROVED_IDS):
        raise ValueError("A reviewed DOI is missing or unresolved")
    changes = []
    for sid in sorted(APPROVED_IDS, key=lambda value: int(value[1:])):
        source = by_id[sid]
        row = rows[sid]
        if row["registry_doi"].lower() != source["identifiers"]["doi"].lower():
            raise ValueError(f"DOI mismatch for {sid}")
        old = source["издание"]
        new = edition(row)
        if old == new:
            continue
        source["издание"] = new
        source["field_resolution"]["издание"].update({
            "state": "reported", "value": new,
            "reason": "Volume, issue and article/page number confirmed in the primary Crossref DOI registration; this is a bibliographic update only.",
            "checked_at": DATE,
            "locators": [{"url": row["query_url"], "locator": "message.container-title, volume, issue, page, article-number"}],
        })
        changes.append({"source_id": sid, "old_edition": old, "new_edition": new, "url": row["query_url"]})
    sweep["bibliographic_updates"] = changes
    sweep["meta"]["reviewed_edition_updates"] = len(changes)
    sweep["manual_review_flags"] = [
        {
            "source_id": "S066",
            "issue": "Crossref update-to and updated-by both point to the same DOI with type new_version dated 2026-05-07.",
            "boundary": "The live PLOS page checked 2026-09-25 does not itself identify a separate correction DOI. Treat this as a version/registry relation requiring publisher-level resolution, not proof of a retraction or correction.",
            "locators": [
                {"url": rows["S066"]["query_url"], "locator": "message.update-to and updated-by"},
                {"url": "https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1012122", "locator": "article header and publication information"},
            ],
        }
    ]
    sweep["remaining"].append("Resolve S066 self-referential Crossref new_version relation against publisher provenance")
    return records, sweep


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, sweep = updated()
    if not args.apply:
        print(f"Dry run: {sweep['meta']['reviewed_edition_updates']} reviewed edition changes")
        return
    snapshot = snapshot_repository(DATA, label="pre-src07-crossref-edition-updates")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-crossref-sweep-2026-09-25.json", sweep)
    print(f"Updated {sweep['meta']['reviewed_edition_updates']} editions; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
