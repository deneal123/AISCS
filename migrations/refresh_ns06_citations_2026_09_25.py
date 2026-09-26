"""Record the first later-dated S149 forward-citation refresh."""

# ruff: noqa: E501 -- retain exact query and locator text.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
WORK = "https://api.openalex.org/works/W7196979222"
CITES = "https://api.openalex.org/works?filter=cites:W7196979222&per-page=25"
CROSSREF = "https://api.crossref.org/works/10.3389/frai.2026.1827727"
PUBLISHER = "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full"


def revised() -> tuple[dict, dict]:
    audit = json.loads((DATA / "ns06-prior-art-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    forward = audit["citation_search"]["s149_forward"]
    if forward["checked_at"] != "2026-09-24" or forward["indexed_cited_by_count"] != 0:
        raise ValueError("S149 citation baseline differs from expected 2026-09-24 audit")
    if any(run["id"] == "NS-RUN-2026-09-25-01" for run in protocol["search_runs"]):
        raise ValueError("2026-09-25 search run already exists")
    forward["dated_refreshes"] = [
        {
            "date": "2026-09-24",
            "indexed_cited_by_count": 0,
            "new_direct_analogue": False,
            "new_mechanism_class": False,
            "status": "initial_pass",
        },
        {
            "date": DATE,
            "indexed_cited_by_count": 0,
            "new_direct_analogue": False,
            "new_mechanism_class": False,
            "status": "first_later_dated_refresh",
            "coverage_limit": "OpenAlex record updated 2026-09-24; Crossref record last indexed 2026-08-07. Zero indexed citations is not zero actual citations.",
        },
    ]
    forward["checked_at"] = DATE
    forward["locators"].extend(
        [
            {
                "url": WORK,
                "section": "cited_by_count=0; updated_date=2026-09-24T07:57:37Z, retrieved 2026-09-25",
            },
            {
                "url": CITES,
                "section": "meta.count=0; exact OpenAlex cites filter, retrieved 2026-09-25",
            },
            {
                "url": CROSSREF,
                "section": "is-referenced-by-count=0; indexed date 2026-08-07, retrieved 2026-09-25",
            },
            {
                "url": PUBLISHER,
                "section": "Exact DOI/title and author-search seed; no new citing primary paper found in this pass",
            },
        ]
    )
    audit["meta"]["checked_at"] = DATE
    audit["next_refresh_plan"]["earliest_date"] = "2026-09-26"
    audit["remaining"] = [
        item.replace(
            "Refresh forward citations of S149 on a later dated search; the global saturation rule requires two dated refreshes with no new mechanism class before stream closure.",
            "Perform a second later-dated S149 citation refresh after 2026-09-25; the 2026-09-25 pass is only the first refresh, and search saturation is not established.",
        )
        for item in audit["remaining"]
    ]
    protocol["meta"]["cutoff"] = DATE
    protocol["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-25-01",
            "date": DATE,
            "queries": [
                "OpenAlex forward citations of DOI 10.3389/frai.2026.1827727 / W7196979222",
                "Exact DOI and title Zero-shot multimodal pain estimation via synthetic pain simulation and domain-invariant learning",
                "El Othmani Naouali synthetic pain domain adaptation 2026",
                "Crossref citation count and relation for DOI 10.3389/frai.2026.1827727",
            ],
            "primary_urls": [PUBLISHER, WORK, CITES, CROSSREF],
            "new_mechanism_classes": [],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    return audit, protocol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol = revised()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns06-first-dated-citation-refresh")
        atomic_write_json(DATA / "ns06-prior-art-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        print(f"Recorded first later-dated S149 citation refresh; snapshot: {snapshot}")
    else:
        print("Dry run: first later-dated S149 refresh ready; PA-03 remains open")


if __name__ == "__main__":
    main()
