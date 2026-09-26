"""Date a repeated legal-access search for the S088 IEEE method."""

# ruff: noqa: E501 -- preserve exact access and scope boundaries.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = DATA / "ns06-prior-art-audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    entry = next(x for x in audit["analogue_decisions"] if x["source_id"] == "S088")
    if entry["certainty"] != "title_only" or "second_access_review" in entry:
        raise ValueError("S088 access state changed")
    entry["second_access_review"] = {
        "checked_at": "2026-09-25",
        "locators": [
            {"url": "https://api.crossref.org/works/10.1109/ISDA70544.2026.11606012", "locator": "message.resource.primary.URL: IEEE document 11606012; link intended for similarity checking, not reader access"},
            {"url": "https://ieeexplore.ieee.org/document/11606012/", "locator": "Publisher document request: HTTP 202, empty body in this environment"},
            {"url": "https://api.openalex.org/works/W7169883718", "locator": "Open-access index reports closed and no repository full text; discovery/access evidence only"},
        ],
        "author_copy_search": "No indexed author manuscript, preprint or institutional deposit with the full method was found in the bounded search.",
        "decision": "The full method remains unavailable. Retain title_only; do not infer cohort, split, augmentation leakage or quantitative results from title or abstract.",
    }
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s088-second-access-review")
        atomic_write_json(path, audit)
        print(f"Recorded S088 access review; snapshot: {snapshot}")
    else:
        print("Dry run: S088 remains title_only")


if __name__ == "__main__":
    main()
