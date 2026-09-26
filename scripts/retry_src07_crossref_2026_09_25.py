"""Retry only the 2026 Crossref rows left unresolved by the first sweep."""

# ruff: noqa: E501 -- retain exact registry fields and status boundaries.

import argparse
import json
import subprocess
import time
from pathlib import Path

from scripts.sweep_2026_crossref_versions import date_parts
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INPUT = DATA / "src07-crossref-sweep-2026-09-25.json"
OUTPUT = DATA / "src07-crossref-retry-2026-09-25.json"


def retry(row: dict) -> dict:
    url = row["query_url"]
    result = subprocess.run(
        ["curl.exe", "-L", "-sS", "--max-time", "25", "-A", "AspaResearch/1.0 (scholarly metadata verification)", "-w", "\n%{http_code}", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    body, _, code = result.stdout.rpartition("\n")
    item = {
        "source_id": row["source_id"], "doi": row["doi"], "query_url": url,
        "initial_http_status": row.get("http_status"), "retry_http_status": code,
        "status": "unresolved",
    }
    if result.returncode or code != "200":
        item["error"] = f"curl_exit={result.returncode}; http={code}; {result.stderr[:180]}"
        return item
    try:
        work = json.loads(body)["message"]
    except (ValueError, KeyError) as exc:
        item["error"] = f"Invalid Crossref payload: {exc}"
        return item
    if work.get("DOI", "").lower() != row["doi"].lower():
        item["error"] = f"Crossref DOI mismatch: {work.get('DOI')}"
        return item
    item.update({
        "status": "crossref_resolved", "registry_doi": work.get("DOI"),
        "title": (work.get("title") or [None])[0],
        "container_title": (work.get("container-title") or [None])[0],
        "type": work.get("type"),
        "published_online": date_parts(work, "published-online"),
        "published_print": date_parts(work, "published-print"),
        "published": date_parts(work, "published"),
        "volume": work.get("volume"), "issue": work.get("issue"),
        "page": work.get("page"), "article_number": work.get("article-number"),
        "relation": work.get("relation") or {},
        "update_to": work.get("update-to") or [],
        "updated_by": work.get("updated-by") or [],
        "publisher": work.get("publisher"),
        "resource_primary_url": (work.get("resource") or {}).get("primary", {}).get("URL"),
        "boundary": "Empty registry relation fields do not prove no correction or journal version elsewhere.",
    })
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and OUTPUT.exists():
        raise ValueError(f"Dated retry audit already exists: {OUTPUT}")
    sweep = json.loads(INPUT.read_text(encoding="utf-8"))
    unresolved = [row for row in sweep["rows"] if row["status"] == "unresolved"]
    if not args.apply:
        print(f"Dry run: {len(unresolved)} Crossref rows to retry sequentially")
        return
    rows = []
    for index, row in enumerate(unresolved):
        if index:
            time.sleep(1)
        rows.append(retry(row))
    audit = {
        "meta": {
            "schema_version": "1.0.0", "checked_at": "2026-09-25",
            "scope": "Sequential retry of unresolved 2026 DOI records from first Crossref sweep",
            "candidates": len(unresolved),
            "resolved": sum(row["status"] == "crossref_resolved" for row in rows),
            "status": "metadata_retry_only",
            "boundary": "Crossref edition and relation fields require scientific and publisher review before canonical updates.",
        },
        "rows": rows,
    }
    snapshot = snapshot_repository(DATA, label="pre-src07-crossref-retry")
    atomic_write_json(OUTPUT, audit)
    print(json.dumps({"snapshot": str(snapshot), **audit["meta"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
