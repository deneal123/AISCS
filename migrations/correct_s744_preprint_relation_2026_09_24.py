"""Remove an incorrectly attributed S744 preprint relation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
WRONG = "doi:10.1101/2023.05.02.539144"


def corrected_records() -> dict:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S744")
    if len(source["relations"]) != 1 or source["relations"][0]["external_id"] != WRONG:
        raise ValueError("S744 relation differs from the expected erroneous baseline")
    source["relations"] = []
    source["validation"]["notes"] += (
        " A prior relation to bioRxiv 10.1101/2023.05.02.539144 was removed: "
        "that preprint is Shiu et al., a distinct adult-brain model. BioRxiv "
        "10.1101/2023.03.11.532232 matches Lappalainen et al. by title and authors, "
        "but a formal publisher-declared version link was not verified."
    )
    resolution = source["field_resolution"]["validation.notes"]
    resolution["value"] = source["validation"]["notes"]
    resolution["reason"] = (
        "Wrong preprint identity corrected by checking both primary bioRxiv records."
    )
    resolution["checked_at"] = "2026-09-24"
    resolution["locators"] = [
        {
            "url": "https://www.biorxiv.org/content/10.1101/2023.05.02.539144v1",
            "locator": "Title and authors: Shiu et al., leaky integrate-and-fire adult brain model",
        },
        {
            "url": "https://www.biorxiv.org/content/10.1101/2023.03.11.532232v1",
            "locator": "Title and authors: Lappalainen et al., visual-system network",
        },
    ]
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = corrected_records()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s744-preprint-relation-correction")
        atomic_write_json(DATA / "records.json", records)
        print(f"Removed incorrect S744 relation; snapshot: {snapshot}")
    else:
        print("Dry run: S744 preprint relation correction ready")


if __name__ == "__main__":
    main()
