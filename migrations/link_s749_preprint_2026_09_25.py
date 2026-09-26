"""Link the registry-asserted preprint to S749's journal version."""

# ruff: noqa: E501 -- keep registry relation and version scope explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DOI = "https://doi.org/10.3390/jcm10204764"
CROSSREF = "https://api.crossref.org/works/10.3390/jcm10204764"
PREPRINT = "https://api.crossref.org/works/10.20944/preprints202109.0010.v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = DATA / "records.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    source = next(x for x in records["sources"] if x["id"] == "S749")
    if source["relations"]:
        raise ValueError("S749 relations changed")
    source["relations"] = [{
        "type": "version_of",
        "target_id": None,
        "external_id": "doi:10.20944/preprints202109.0010.v1",
        "note": "Crossref journal has-preprint and preprint is-preprint-of both identify the 1 September 2021 preprints.org v1; this is the same study, not independent clinical evidence.",
    }]
    source["identifiers"]["exact_url"] = DOI
    source["field_resolution"]["identifiers.exact_url"].update(
        value=DOI,
        reason="The DOI resolves to the journal version; the PMC full text remains a primary locator.",
        checked_at="2026-09-25",
        locators=[{"url": CROSSREF, "locator": "journal DOI, container and relation.has-preprint"}, {"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8538165/", "locator": "journal full-text mirror"}],
    )
    source["validation"]["notes"] += " Crossref links this journal article to preprints.org v1 DOI 10.20944/preprints202109.0010.v1; registry checks on 2026-09-25 found no correction or retraction notice."
    source["field_resolution"]["validation.notes"].update(
        value=source["validation"]["notes"],
        reason="Crossref bidirectional version relation and PubMed/Europe PMC update metadata reviewed.",
        checked_at="2026-09-25",
        locators=[
            {"url": CROSSREF, "locator": "relation.has-preprint; no update-to or updated-by"},
            {"url": PREPRINT, "locator": "relation.is-preprint-of; posted-content v1"},
            {"url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8538165/fullTextXML", "locator": "is-retracted=no"},
        ],
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s749-preprint-link")
        atomic_write_json(path, records)
        print(f"Linked S749 preprint; snapshot: {snapshot}")
    else:
        print("Dry run: S749 preprint relation verified")


if __name__ == "__main__":
    main()
