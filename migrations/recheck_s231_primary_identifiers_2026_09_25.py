"""Correct S231 identifiers and access from the primary Europe PMC JATS record."""

# ruff: noqa: E501 -- preserve exact primary URLs, JSON field locators and scientific boundaries.

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
JATS = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13210900/fullTextXML"
CROSSREF = "https://api.crossref.org/works/10.3390%2Fs26103049"


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S231")
    if source["identifiers"]["doi"] is not None or source["identifiers"]["pmid"] is not None:
        raise ValueError("S231 identifiers already reviewed")

    fields = {
        "авторы": ("Sun, Zhengdi; Mu, Anle; Hao, Fuxiang; Wang, Hang", "article-meta/contrib-group/contrib/name; message.author"),
        "издание": ("Sensors 26(10):3049", "article-meta/volume and issue; message.volume, issue, page"),
    }
    for key, (value, locator) in fields.items():
        source[key] = value
        source["field_resolution"][key].update({
            "state": "reported", "value": value,
            "reason": "Bibliographic detail confirmed in the primary JATS article and DOI registration.",
            "checked_at": DATE,
            "locators": [{"url": JATS, "locator": locator}, {"url": CROSSREF, "locator": locator}],
        })

    for kind, value in (("doi", "10.3390/s26103049"), ("pmid", "42197858")):
        source["identifiers"][kind] = value
        source["field_resolution"][f"identifiers.{kind}"].update({
            "state": "reported", "value": value,
            "reason": "Identifier is explicit in the primary JATS article-meta/article-id elements.",
            "checked_at": DATE,
            "locators": [{"url": JATS, "locator": f"article-meta/article-id[@pub-id-type='{kind}']"}],
        })

    source["evidence"]["access_status"] = "open"
    source["field_resolution"]["evidence.access_status"].update({
        "state": "reported", "value": "open",
        "reason": "Full publisher article is available as open primary JATS through Europe PMC; direct PMC HTML displayed reCAPTCHA in this environment.",
        "checked_at": DATE,
        "locators": [{"url": JATS, "locator": "article/front and article/body full text"}],
    })
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE, "source_id": "S231", "status": "primary_jats_checked"},
        "identifiers": {"doi": "10.3390/s26103049", "pmid": "42197858", "pmcid": "PMC13210900"},
        "edition": "Sensors 26(10):3049",
        "article_type": "review-article",
        "locators": [
            {"url": JATS, "locator": "article/@article-type; article-meta/article-id, contrib-group, volume, issue; body"},
            {"url": CROSSREF, "locator": "message.DOI, author, volume, issue, page, relation, update-to"},
        ],
        "correction_boundary": "Crossref relation and update-to fields were empty on this dated check; this does not prove absence of a correction in every registry.",
        "scientific_boundary": "This is a broad review without new participants or a patient-level ECAP-to-pain outcome dataset.",
    }
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = updated()
    if not args.apply:
        print("Dry run: S231 DOI, PMID, authors, edition and primary access corrected")
        return
    snapshot = snapshot_repository(DATA, label="pre-s231-primary-identifiers")
    atomic_write_json(DATA / "records.json", records)
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    atomic_write_json(DATA / "completeness-report.json", completeness)
    atomic_write_json(DATA / "src07-s231-primary-recheck-2026-09-25.json", audit)
    print(f"Updated S231; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
