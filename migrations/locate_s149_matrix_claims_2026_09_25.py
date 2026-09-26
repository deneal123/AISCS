"""Replace generic S149 evidence locators with publisher sections and tables."""

# ruff: noqa: E501 -- exact scientific boundaries and section locators are intentional.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full"


def updated() -> tuple[dict, dict]:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    rows = [row for row in matrix["rows"] if row["batch_id"] == "batch-001" and row["source_ids"] == ["S149"]]
    if len(rows) != 2 or any(row["locators"][0]["locator"] != "validated evidence row" for row in rows):
        raise ValueError("Unexpected S149 evidence-matrix starting state")
    for row in rows:
        if "96%" in row["claim"]:
            row["locators"] = [
                {"source_id": "S149", "url": URL, "locator": "Section 5.2 and Tables 9-11: dataset-specific UNBC MAE 0.89, BioVid accuracy 78.3%, neonatal accuracy 81.5%; no reported 96% headline for this method"},
            ]
            row["limitations"] = "The imported registry provided no primary locator for 96%; the checked paper's Section 5.2 and Tables 9-11 report different dataset-specific metrics. Do not turn absence of a matching headline into a performance result."
        else:
            row["locators"] = [
                {"source_id": "S149", "url": URL, "locator": "Sections 2.4, 3.4-3.5 and 4.1: labeled synthetic source plus unlabeled real target alignment; no real target pain labels in training"},
                {"source_id": "S149", "url": URL, "locator": "Section 5.2, Tables 9-11: UNBC MAE 0.89, BioVid accuracy 78.3%, neonatal accuracy 81.5%"},
                {"source_id": "S149", "url": URL, "locator": "Section 6.8: all three datasets used as unlabeled real data in at least one condition; no independent external validation"},
            ]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25", "status": "two_s149_locators_reviewed"},
        "source_id": "S149",
        "publisher_url": URL,
        "claims_reviewed": 2,
        "boundary": "These primary locators support only synthetic-source unsupervised domain adaptation on tested retrospective benchmarks. They do not demonstrate clinical deployment or fly-to-human transfer. The unlocated 96% imported claim remains prohibited.",
    }
    return matrix, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix, audit = updated()
    if not args.apply:
        print("Dry run: two S149 evidence locators reviewed")
        return
    snapshot = snapshot_repository(DATA, label="pre-s149-evidence-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s149-evidence-locator-review-2026-09-25.json", audit)
    print(f"Updated two S149 locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
