"""Replace four generic Drosophila evidence locators with primary fragments."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DOOM = "https://github.com/nftechie/doomfly/blob/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33/README.md"


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    selected = [
        row for row in matrix["rows"]
        if row["source_ids"] in (["S090"], ["S200"], ["S368"])
        and row["locators"][0]["locator"] == "validated evidence row"
    ]
    if len(selected) != 4:
        raise ValueError("Expected four generic Drosophila rows")
    for row in selected:
        source_id = row["source_ids"][0]
        if source_id == "S090":
            url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC11787400/"
            locator = (
                "Abstract and METHOD, Fly Husbandry and Cross Preparation: "
                "ChR2 in class-IV sensory neurons; third-instar larval rolling assay."
            )
        elif source_id == "S368":
            url = "https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/"
            locator = (
                "Project article, introduction and visuals 1-3: adult male "
                "brain plus ventral nerve cord; more than 166,000 neurons."
            )
        else:
            url = DOOM
            locator = (
                "Pinned README, Status and The loop: MaleCNS/ViZDoom interface; "
                "v6 visual, conditioning and survival gates failed."
            )
        row["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": ["S090", "S200", "S368"],
        "rows_reviewed": 4,
        "status": "primary_fragments_located",
        "boundary": "The larval protocol measures rolling, the Google article "
        "describes an anatomical map, and DOOMFLY reports failed learning gates. "
        "None is evidence of subjective pain or human transfer.",
    }
    snapshot = snapshot_repository(DATA, label="pre-three-drosophila-source-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "three-drosophila-source-locator-review-2026-09-25.json", audit)
    print(f"Updated four Drosophila rows; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
