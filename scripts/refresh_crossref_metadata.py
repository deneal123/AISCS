"""Refresh bibliographic fields for metadata-only DOI records from Crossref."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from service.completeness import completeness_summary
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"


def format_authors(authors: list[dict[str, Any]]) -> str | None:
    values = [
        " ".join(part for part in (author.get("given"), author.get("family")) if part).strip()
        for author in authors
    ]
    values = [value for value in values if value]
    return "; ".join(values) or None


def crossref_work(doi: str) -> dict[str, Any]:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "aspa-research/1.3 (mailto:research@example.invalid)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
        return {"ok": True, "url": url, "message": payload["message"]}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def _year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def _set_reported(
    record: dict[str, Any], path: str, value: Any, *, url: str, locator: str
) -> None:
    record["field_resolution"][path] = {
        "state": "reported",
        "value": value,
        "reason": "Bibliographic value confirmed in the Crossref record for the canonical DOI.",
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


def refresh(*, apply: bool, data_dir: Path = DATA) -> dict[str, Any]:
    records = load_json(data_dir / "records.json")
    audit = load_json(data_dir / "audit-report.json")
    validation_log = load_json(data_dir / "validation-log.json")
    targets = [
        source
        for source in records["sources"]
        if source["validation"]["status"] == "verified_metadata"
        and source["identifiers"].get("doi")
    ]
    results: list[dict[str, Any]] = []
    for source in targets:
        response = crossref_work(source["identifiers"]["doi"])
        item = {"source_id": source["id"], "doi": source["identifiers"]["doi"], **response}
        results.append(item)
        if not response["ok"]:
            continue
        message = response["message"]
        authors = format_authors(message.get("author") or [])
        year = _year(message)
        venue = next(iter(message.get("container-title") or []), None) or message.get(
            "publisher"
        )
        if authors:
            source["авторы"] = authors
            _set_reported(
                source,
                "авторы",
                authors,
                url=response["url"],
                locator="message.author",
            )
        if year:
            source["год"] = year
            _set_reported(
                source,
                "год",
                year,
                url=response["url"],
                locator="message.published/issued.date-parts",
            )
        if venue:
            source["издание"] = venue
            _set_reported(
                source,
                "издание",
                venue,
                url=response["url"],
                locator="message.container-title or message.publisher",
            )
        source["validation"]["checked_at"] = DATE
        _set_reported(
            source,
            "validation.checked_at",
            DATE,
            url=response["url"],
            locator="Crossref DOI recheck",
        )
        if message.get("relation") or message.get("update-to") or message.get("updated-by"):
            note = "Crossref reports a relation/update field; manual version review is required."
            if note not in source["validation"]["notes"]:
                source["validation"]["notes"] = f"{source['validation']['notes']} {note}".strip()
                _set_reported(
                    source,
                    "validation.notes",
                    source["validation"]["notes"],
                    url=response["url"],
                    locator="message.relation/update-to/updated-by",
                )

    records["meta"]["updated_at"] = DATE
    successful = sum(item["ok"] for item in results)
    audit["crossref_metadata_refresh"] = {
        "checked_at": DATE,
        "targets": len(results),
        "resolved": successful,
        "failed_source_ids": [item["source_id"] for item in results if not item["ok"]],
        "boundary": "Crossref confirms bibliography only; it does not upgrade full-text validation.",
    }
    audit["meta"]["generated_at"] = DATE
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "CROSSREF-2026-09-24-01",
            "date": DATE,
            "stream": "metadata-only DOI refresh",
            "query": "Crossref /works/{doi} for every verified_metadata DOI record",
            "urls_reviewed": [item["url"] for item in results],
            "source_ids": [item["source_id"] for item in results],
            "decision": "bibliographic refresh only; full-text status unchanged",
        }
    )
    validation_log["meta"]["checked_at"] = DATE
    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(records["sources"]))
    completeness["meta"]["generated_at"] = DATE

    result = {
        "ok": True,
        "applied": False,
        "targets": len(results),
        "resolved": successful,
        "failed": [item for item in results if not item["ok"]],
    }
    if not apply:
        return result
    snapshot = snapshot_repository(data_dir, label="pre-crossref-metadata-refresh")
    atomic_write_json(data_dir / "records.json", records)
    atomic_write_json(data_dir / "audit-report.json", audit)
    atomic_write_json(data_dir / "validation-log.json", validation_log)
    atomic_write_json(data_dir / "completeness-report.json", completeness)
    report = validate_repository(data_dir)
    if not report["ok"]:
        raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": report})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(refresh(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
