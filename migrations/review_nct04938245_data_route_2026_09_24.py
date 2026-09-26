"""Record the primary article's request route for the UMN ECAP data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
PDF = "https://iopscience.iop.org/article/10.1088/1741-2552/adbfbe/pdf"


def revised_audit() -> dict:
    audit = json.loads((DATA / "human-ecap-scs-access-audit.json").read_text(encoding="utf-8"))
    entry = next(item for item in audit["candidates"] if item["trial_id"] == "NCT04938245")
    if entry["decision"] != "planned_release_not_yet_located":
        raise ValueError("NCT04938245 decision differs from expected baseline")
    entry["decision"] = "request_route_documented_release_not_located"
    access = entry["checks"]["access_procedure"]
    access["state"] = "partial"
    access["finding"] = (
        "The owner-submitted registry promises anonymized data in Zenodo or an equivalent "
        "repository for five years, but an exact trial-ID search located no accession on "
        "2026-09-24. The published study instead states that its data are available from "
        "the corresponding author on request, subject to ethics or IRB restrictions. "
        "The owner has not confirmed the field list or suitability for this project."
    )
    access["locators"].append(
        {"url": PDF, "locator": "König et al. 2025, Data availability statement"}
    )
    entry["owner_questions"].insert(
        0,
        "Can the corresponding author provide data under the article's request policy, "
        "and how does that route relate to the planned public repository release?",
    )
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit = revised_audit()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-nct04938245-data-route-review")
        atomic_write_json(DATA / "human-ecap-scs-access-audit.json", audit)
        print(f"Updated NCT04938245 access route; snapshot: {snapshot}")
    else:
        print("Dry run: NCT04938245 request route ready; no usable dataset established")


if __name__ == "__main__":
    main()
