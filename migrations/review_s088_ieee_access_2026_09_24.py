"""Record the IEEE full-text access boundary for S088 without inferring methods."""

# ruff: noqa: E501 -- exact publisher endpoints and access observations.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
CROSSREF = "https://api.crossref.org/works/10.1109/ISDA70544.2026.11606012"
IEEE = "https://ieeexplore.ieee.org/document/11606012"
PDF = "https://ieeexplore.ieee.org/ielx8/11605974/11605976/11606012.pdf?arnumber=11606012"


def update() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ns06-prior-art-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S088")
    decision = next(item for item in audit["analogue_decisions"] if item["source_id"] == "S088")
    if "primary_access_review" in decision:
        raise ValueError("S088 access review already applied")
    if source["validation"]["full_text_status"] != "unavailable":
        raise ValueError("S088 full-text status changed")

    decision["primary_access_review"] = {
        "checked_at": DATE,
        "crossref": {
            "url": CROSSREF,
            "locator": "message.resource.primary.URL identifies IEEE document 11606012; message.link[0] lists a version-of-record PDF for similarity checking; abstract is absent",
            "result": "Publisher metadata identifies a PDF location but does not disclose method, datasets or metrics.",
        },
        "publisher_document": {
            "url": IEEE,
            "result": "HTTP 202 with an empty response in this environment",
        },
        "publisher_pdf": {
            "url": PDF,
            "result": "HTTP 418 from both IEEE document PDF path and Crossref-listed staging host in this environment",
        },
        "decision": "Keep S088 title_only, full_text_status=unavailable, and all protocol fields unresolved; the Crossref similarity-checking link is not evidence of lawful readable access or of the method.",
    }
    source["validation"]["notes"] = (
        "Crossref confirms title, authors, venue and DOI and lists an IEEE version-of-record PDF link for similarity checking, but supplies no abstract. "
        "IEEE document endpoint returned HTTP 202 with no body, and publisher PDF endpoints returned HTTP 418 on 2026-09-24. "
        "Dataset, cohort, modalities, split, metrics and claimed state of the art remain unverified."
    )
    source["field_resolution"]["validation.notes"] = {
        "state": "reported",
        "value": source["validation"]["notes"],
        "reason": "Primary metadata and publisher access responses checked; no method inferred.",
        "checked_at": DATE,
        "locators": [
            {"url": CROSSREF, "locator": "message.resource.primary, message.link[0], and missing abstract"},
            {"url": IEEE, "locator": "document 11606012 access attempt: HTTP 202, empty body"},
            {"url": PDF, "locator": "publisher PDF access attempt: HTTP 418"},
        ],
    }
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s088-ieee-access-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "ns06-prior-art-audit.json", audit)
        print(f"Applied S088 access review; snapshot: {snapshot}")
    else:
        print("Dry run: IEEE metadata and PDF endpoints checked; S088 remains title-only")


if __name__ == "__main__":
    main()
