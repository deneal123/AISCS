"""Resolve S740 preprint version from its primary PMC JATS deposit."""

# ruff: noqa: E501 -- retain exact JATS version locator and scope distinction.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13142387/fullTextXML"
EDITION = "bioRxiv preprint v2 (30 April 2026; PMC13142387.2)"


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S740")
    if source["издание"] != "bioRxiv" or source["identifiers"]["doi"] != "10.1101/2025.09.12.675944":
        raise ValueError("S740 card changed")
    source["издание"] = EDITION
    source["field_resolution"]["издание"].update({
        "state": "reported", "value": EDITION,
        "reason": "The primary preprint JATS explicitly records article-version type number 2 and PMCID version PMC13142387.2; epub is 30 April 2026. The DOI date in 2025 identifies the original deposit, not this version.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": "article-meta: article-version[number]=2; article-id[pmcid-ver]=PMC13142387.2; pub-date[epub]=30 April 2026"}],
    })
    source["validation"]["notes"] += " SRC-07 2026-09-25: PMC JATS for the author preprint explicitly has article-version number 2 and PMCID version PMC13142387.2, dated 30 April 2026. Crossref's 2025 DOI date is the initial deposit date; no journal identity follows from this JATS."
    source["field_resolution"]["validation.notes"].update({
        "state": "reported", "value": source["validation"]["notes"],
        "reason": "Primary PMC JATS version and DOI chronology checked without inferring a journal publication.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": "article-meta article-version, article-id and epub date"}],
    })
    audit = json.loads((DATA / "src07-version-recheck-audit.json").read_text(encoding="utf-8"))
    audit["entries"].append({
        "source_id": "S740",
        "current_version": "author preprint v2, 30 April 2026",
        "source_url": URL,
        "access_boundary": "Primary PMC JATS version number and publication date; bioRxiv page may rate-limit direct requests",
        "correction_retraction_check": "JATS marks the record as preprint and contains no journal correction; this does not prove that no later notice exists.",
        "preprint_journal_relation": "No journal article is established by this primary preprint version record.",
    })
    audit["meta"]["scope"] = "SRC-07 seven 2026 source-version rechecks"
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = updated()
    if not args.apply:
        print("Dry run: S740 preprint v2 from PMC JATS")
        return
    snapshot = snapshot_repository(DATA, label="pre-s740-pmc-preprint-version")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-version-recheck-audit.json", audit)
    print(f"Recorded S740 v2; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
