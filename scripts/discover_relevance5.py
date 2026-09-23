"""Query primary bibliographic registries for unresolved relevance-5 records.

The script only writes discovery evidence. It never changes canonical records.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.core import load_json  # noqa: E402
from service.pipeline import atomic_write_json  # noqa: E402

DATA = ROOT / "data"
OUT = DATA / "curation" / "relevance-5" / "discovery"
USER_AGENT = "AspaResearchCuration/1.0 (mailto:research@example.invalid)"


def normalized(value: str) -> str:
    value = re.sub(r"\((?:final|extended|final extended)\)", "", value, flags=re.I)
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(value.split())


def similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, normalized(left), normalized(right)).ratio(), 4)


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def crossref(title: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "query.title": title,
            "rows": 5,
            "select": "DOI,title,author,published-online,published-print,container-title,URL,type",
        }
    )
    url = f"https://api.crossref.org/works?{query}"
    result: dict[str, Any] = {"service": "Crossref", "query": title, "url": url}
    try:
        items = fetch_json(url).get("message", {}).get("items", [])
        candidates = []
        for item in items:
            candidate_title = " ".join(item.get("title") or [])
            authors = [
                " ".join(filter(None, (author.get("given"), author.get("family"))))
                for author in item.get("author", [])
            ]
            issued = item.get("published-print") or item.get("published-online") or {}
            parts = issued.get("date-parts") or []
            candidates.append(
                {
                    "title": candidate_title,
                    "similarity": similarity(title, candidate_title),
                    "doi": item.get("DOI"),
                    "authors": authors,
                    "year": parts[0][0] if parts and parts[0] else None,
                    "container_title": " ".join(item.get("container-title") or []),
                    "primary_url": item.get("URL"),
                    "type": item.get("type"),
                }
            )
        result.update({"status": "ok", "candidates": candidates})
    except (OSError, urllib.error.URLError, ValueError) as exc:
        result.update({"status": "error", "error": str(exc), "candidates": []})
    return result


def pubmed(title: str) -> dict[str, Any]:
    query = f'"{title}"[Title]'
    params = urllib.parse.urlencode({"db": "pubmed", "term": query, "retmode": "json", "retmax": 5})
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
    result: dict[str, Any] = {"service": "PubMed", "query": query, "url": url}
    try:
        ids = fetch_json(url).get("esearchresult", {}).get("idlist", [])
        candidates = []
        if ids:
            summary_url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
                + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
            )
            summaries = fetch_json(summary_url).get("result", {})
            for pmid in ids:
                item = summaries.get(pmid, {})
                candidate_title = item.get("title", "")
                candidates.append(
                    {
                        "title": candidate_title,
                        "similarity": similarity(title, candidate_title),
                        "pmid": pmid,
                        "authors": [author.get("name") for author in item.get("authors", [])],
                        "year": (item.get("pubdate") or "")[:4] or None,
                        "container_title": item.get("fulljournalname"),
                        "primary_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    }
                )
        result.update({"status": "ok", "candidates": candidates})
    except (OSError, urllib.error.URLError, ValueError, ET.ParseError) as exc:
        result.update({"status": "error", "error": str(exc), "candidates": []})
    return result


def discover(record: dict[str, Any]) -> dict[str, Any]:
    title = record["название"]
    stripped = re.sub(r"\s*\((?:final|extended|final extended)\)\s*$", "", title, flags=re.I)
    attempts = [crossref(stripped), pubmed(stripped)]
    best = max(
        (candidate for attempt in attempts for candidate in attempt.get("candidates", [])),
        key=lambda item: item.get("similarity", 0),
        default=None,
    )
    return {
        "source_id": record["id"],
        "title": title,
        "year": record.get("год"),
        "source_type": record.get("тип_источника"),
        "attempts": attempts,
        "best_candidate": best,
        "exact_candidate": bool(best and best.get("similarity", 0) >= 0.93),
    }


def main() -> None:
    records = load_json(DATA / "records.json").get("sources", [])
    targets = [
        record
        for record in records
        if record.get("релевантность") == 5
        and record.get("validation", {}).get("status") == "unverified"
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(discover, record): record["id"] for record in targets}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # preserve a complete audit trail even on one failure
                results.append(
                    {
                        "source_id": futures[future],
                        "attempts": [],
                        "best_candidate": None,
                        "exact_candidate": False,
                        "error": str(exc),
                    }
                )
            time.sleep(0.02)
    results.sort(key=lambda item: int(item["source_id"][1:]))
    payload = {
        "meta": {
            "version": "1.0.0",
            "generated_at": date.today().isoformat(),
            "scope": "unverified relevance-5 canonical records",
            "source_count": len(results),
            "exact_candidate_count": sum(item.get("exact_candidate", False) for item in results),
            "method": "Crossref title query plus exact-title PubMed query; candidates are not accepted automatically.",
        },
        "results": results,
    }
    atomic_write_json(OUT / "registry-search.json", payload)
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
