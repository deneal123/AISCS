"""Pin the FANC Nature paper's materialization without assigning it to S740."""

# ruff: noqa: E501 -- exact release and scope locators remain explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
WIKI = "https://github.com/htem/FANC_auto_recon/wiki/Connectomic-reconstruction-of-a-female-Drosophila-ventral-nerve-cord-(Azevedo,-Lesser,-Phelps,-Mark-et-al.-2024-Nature)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    source = next(x for x in records["sources"] if x["id"] == "S773")
    entry = next(x for x in audit["entries"] if x["source_id"] == "S773")
    row = next(x for x in matrix["rows"] if x["source_ids"] == ["S773", "S774"])
    version = entry["extraction"]["connectome_version"]
    if version["state"] != "not_reported":
        raise ValueError("S773 release state changed")
    version.update(
        state="reported",
        value="FANC CAVE materialization v840 (timestamp 1705479001.179472; 17 January 2024)",
        reason="The author-maintained FANC wiki explicitly pins the Nature paper's analysis to this CAVE materialization; it does not identify S740's later processed FANC matrix input.",
        checked_at=DATE,
        locators=[{"url": WIKI, "locator": "Paragraph below publication and analysis-code links: 17 January 2024, CAVE materialization v840, timestamp 1705479001.179472"}],
    )
    source["датасет"] = source["датасет"].replace(
        "The accessible publisher page does not pin a CAVE/source-connectome release identifier.",
        "The author-maintained FANC wiki pins this Nature paper's analysis to CAVE materialization v840 on 17 January 2024; S740's FANC input export remains unpinned.",
    )
    source["field_resolution"]["датасет"].update(
        value=source["датасет"],
        reason="The author FANC wiki pins the Nature analysis only; S740's export must be assessed separately.",
        checked_at=DATE,
        locators=[{"url": WIKI, "locator": "Nature paper analysis: CAVE materialization v840, timestamp 1705479001.179472"}],
    )
    source["ограничения"] = source["ограничения"].replace(
        "A named FANC dataset is not a pinned export/release for S740's FANC input.",
        "The author wiki pins the Nature analysis to CAVE v840, but S740's processed FANC matrix has no documented materialization and must not inherit v840.",
    )
    source["field_resolution"]["ограничения"].update(
        value=source["ограничения"],
        reason="Published study release and S740 input provenance are distinct.",
        checked_at=DATE,
        locators=[{"url": WIKI, "locator": "Nature study's CAVE v840 only"}],
    )
    row["verified_evidence"] += " Author FANC wiki pins S773's own analysis to CAVE materialization v840 (17 January 2024)."
    row["limitations"] = row["limitations"].replace(
        "Neither primary article pins the immutable exported input used by S740.",
        "S773's v840 applies to the Nature study; neither S773 nor S774 pins the immutable exported inputs used by S740.",
    )
    row["locators"].append({"source_id": "S773", "url": WIKI, "locator": "Nature study analysis release: CAVE materialization v840, timestamp 1705479001.179472"})
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s773-fanc-v840-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied FANC v840 review; snapshot: {snapshot}")
    else:
        print("Dry run: S773 study release pinned; S740 input remains open")


if __name__ == "__main__":
    main()
