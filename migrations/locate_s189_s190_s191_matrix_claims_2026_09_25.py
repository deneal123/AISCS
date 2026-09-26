"""Pin three controlled pain-classification benchmark claims to primary pages."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S189": (
        "https://www.mdpi.com/2076-3417/15/9/4804",
        "Article Figure 2 and Figures 5-7: Brain Mediators of Pain EEG, "
        "subject-dependent and cross-subject classification analyses.",
    ),
    "S190": (
        "https://arxiv.org/abs/2507.21886v6",
        "Author preprint v6 abstract: AI4PAIN respiration input, compact "
        "cross-attention transformer and multi-window fusion.",
    ),
    "S191": (
        "https://arxiv.org/abs/2407.19809v1",
        "Author preprint v1 abstract: AI4PAIN facial video and fNIRS, "
        "dual-ViT modality-agnostic fusion, 46.76% multilevel accuracy.",
    ),
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    for source_id, (url, locator) in LOCATORS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic benchmark row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "three_benchmark_locators_reviewed",
        "boundary": "Subject-dependent results and challenge classification "
        "do not establish independent clinical-pain validation.",
    }
    snapshot = snapshot_repository(DATA, label="pre-three-benchmark-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "three-benchmark-locator-review-2026-09-25.json", audit)
    print(f"Updated three benchmark locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
