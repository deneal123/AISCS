"""Batch-check Crossref metadata for 2026 cards without changing source records."""

# ruff: noqa: E501 -- registry field names and audit descriptions are explicit.

import argparse
import json
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"


def date_parts(work: dict, field: str) -> str | None:
    parts = (work.get(field) or {}).get("date-parts") or []
    if not parts or not parts[0]:
        return None
    return "-".join(str(part).zfill(2) for part in parts[0])


def check(source: dict) -> dict:
    doi = source["identifiers"]["doi"]
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    result = subprocess.run(
        ["curl.exe", "-L", "-sS", "--max-time", "18", "-w", "\n%{http_code}", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    body, _, code = result.stdout.rpartition("\n")
    row = {"source_id": source["id"], "doi": doi, "query_url": url, "http_status": code, "status": "unresolved"}
    if result.returncode or code != "200":
        row["error"] = f"curl_exit={result.returncode}; http={code}; {result.stderr[:180]}"
        return row
    try:
        work = json.loads(body)["message"]
    except (ValueError, KeyError) as exc:
        row["error"] = f"Invalid Crossref payload: {exc}"
        return row
    row.update({
        "status": "crossref_resolved",
        "registry_doi": work.get("DOI"),
        "title": (work.get("title") or [None])[0],
        "container_title": (work.get("container-title") or [None])[0],
        "type": work.get("type"),
        "published_online": date_parts(work, "published-online"),
        "published_print": date_parts(work, "published-print"),
        "published": date_parts(work, "published"),
        "volume": work.get("volume"),
        "issue": work.get("issue"),
        "page": work.get("page"),
        "article_number": work.get("article-number"),
        "relation": work.get("relation") or {},
        "update_to": work.get("update-to") or [],
        "updated_by": work.get("updated-by") or [],
        "correction_boundary": "Crossref update fields checked; empty fields do not prove no correction in another registry.",
    })
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    output_path = DATA / "src07-crossref-sweep-2026-09-25.json"
    if args.apply and output_path.exists():
        raise ValueError(f"Dated sweep already exists: {output_path}")
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]
    cohort = [item for item in records if item["год"] == 2026]
    crossref_candidates = [
        item for item in cohort
        if item["identifiers"].get("doi")
        and not item["identifiers"]["doi"].startswith("10.5281/")
    ]
    if not args.apply:
        print(f"Dry run: {len(cohort)} sources from 2026; {len(crossref_candidates)} DOI candidates")
        return
    rows = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(check, source): source["id"] for source in crossref_candidates}
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({"source_id": futures[future], "status": "unresolved", "error": str(exc)})
    rows.sort(key=lambda item: int(item["source_id"][1:]))
    audit = {
        "meta": {
            "schema_version": "1.0.0", "checked_at": DATE,
            "scope": "Crossref metadata and update relations for 2026 canonical records",
            "total_2026_sources": len(cohort),
            "doi_candidates": len(crossref_candidates),
            "crossref_resolved": sum(item["status"] == "crossref_resolved" for item in rows),
            "status": "metadata_sweep_only",
            "boundary": "Crossref does not establish full-text methods, publisher correction coverage, preprint-journal identity or source-data availability.",
        },
        "rows": rows,
        "non_crossref_route_source_ids": [
            item["id"] for item in cohort if item not in crossref_candidates
        ],
        "remaining": [
            "Review changed editions and relation/update fields against primary publisher or repository pages",
            "Check arXiv, bioRxiv, DataCite, patents, code and records without DOI by their authoritative source",
            "Perform later dated full version refresh before SRC-07 closure",
        ],
    }
    snapshot = snapshot_repository(DATA, label="pre-src07-crossref-sweep")
    atomic_write_json(output_path, audit)
    print(json.dumps({"snapshot": str(snapshot), **audit["meta"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
