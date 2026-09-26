"""Clarify FANC segmentation access from the publisher Data availability."""

# ruff: noqa: E501 -- keep the primary access locator explicit.

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://www.nature.com/articles/s41586-024-07389-x"


def main() -> None:
    path = DATA / "records.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    source = next(x for x in records["sources"] if x["id"] == "S773")
    if source["evidence"]["access_status"] != "open":
        raise ValueError("S773 access state changed")
    source["evidence"]["access_status"] = "registration_required"
    source["field_resolution"]["evidence.access_status"].update(
        value="registration_required",
        reason="The publisher states that FANC segmentation is available after joining the FANC community.",
        checked_at="2026-09-25",
        locators=[{"url": URL, "locator": "Data availability: join the FANC community for segmentation"}],
    )
    snapshot = snapshot_repository(DATA, label="pre-s773-fanc-access-correction")
    atomic_write_json(path, records)
    print(f"Corrected S773 access; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
