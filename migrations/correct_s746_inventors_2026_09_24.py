"""Correct S746 inventors against the publication header."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
OLD = (
    "Leonid M. Litvak; Joshua J. Nedrud; Janelle Blum; David Dinsmoor; Juan Manuel Montes Hincapie"
)
NEW = "Leonid M. Litvak; Joshua J. Nedrud"
URL = "https://patents.google.com/patent/WO2025224687A1/en"


def corrected_records() -> dict:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S746")
    author_key = next(key for key, value in source.items() if value == OLD)
    if source["field_resolution"][author_key]["value"] != OLD:
        raise ValueError("S746 author resolution differs from the expected baseline")
    source[author_key] = NEW
    resolution = source["field_resolution"][author_key]
    resolution["value"] = NEW
    resolution["reason"] = (
        "Corrected inventors against the WO2025224687A1 publication header; "
        "three names belonged to a different publication."
    )
    resolution["checked_at"] = "2026-09-24"
    resolution["locators"] = [
        {
            "url": URL,
            "locator": "Publication header, Inventor field: Leonid M. Litvak and Joshua J. Nedrud",
        }
    ]
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = corrected_records()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s746-inventor-correction")
        atomic_write_json(DATA / "records.json", records)
        print(f"Corrected S746 inventor list; snapshot: {snapshot}")
    else:
        print("Dry run: S746 inventor correction ready")


if __name__ == "__main__":
    main()
