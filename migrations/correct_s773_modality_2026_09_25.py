"""Keep the FANC abstract's anatomical modality separate from behavior."""

# ruff: noqa: E501 -- preserve the exact primary-evidence boundary.

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://www.nature.com/articles/s41586-024-07389-x"


def main() -> None:
    path = DATA / "records.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    source = next(x for x in records["sources"] if x["id"] == "S773")
    if source["evidence"]["modalities"] != ["connectome", "behavior"]:
        raise ValueError("S773 modality state changed")
    source["evidence"]["modalities"] = ["connectome"]
    source["field_resolution"]["evidence.modalities"].update(
        value=["connectome"],
        reason="The accessible primary abstract reports EM anatomy and a motor atlas; it does not establish a separate measured behavior modality for this card.",
        checked_at="2026-09-25",
        locators=[{"url": URL, "locator": "Abstract; Figures 1–6 captions"}],
    )
    snapshot = snapshot_repository(DATA, label="pre-s773-modality-correction")
    atomic_write_json(path, records)
    print(f"Corrected S773 modality; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
