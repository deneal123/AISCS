"""Pin five review/context evidence claims to primary text fragments."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S231": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13210900/",
        "Abstract and Introduction, Figure 1: four neuromorphic "
        "neuroengineering domains; fragmented proof-of-concept evidence base.",
    ),
    "S273": (
        "https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adsu.70449",
        "Publisher abstract: sEMG/EDA-responsive TENS prototype, mouse "
        "hot-plate paw-withdrawal result, and future AI roadmap.",
    ),
    "S060": (
        "https://www.jcdr.net/article_fulltext.asp?id=24236&issn=0973-709x&issue=9&page=UE01&volume=20&year=2026",
        "Narrative review, Introduction and limitations/conclusion: "
        "candidate selection, programming, adaptive SCS and validation gaps.",
    ),
    "S022": (
        "https://pubmed.ncbi.nlm.nih.gov/41539462/",
        "Author abstract: composite SCI-pain biomarkers and warning against "
        "physiological features alone omitting psychosocial dimensions.",
    ),
    "S161": (
        "https://pubmed.ncbi.nlm.nih.gov/37219574/",
        "Author abstract: candidate selection, trial response and "
        "programming optimization are surveyed ML applications.",
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
            raise ValueError(f"Expected one generic review row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "five_review_context_locators_reviewed",
        "boundary": "Narrative reviews and the mouse TENS proof of concept "
        "do not establish human SCS efficacy, ECAP as pain, or a validated "
        "fly-to-human transfer.",
    }
    snapshot = snapshot_repository(DATA, label="pre-five-review-claim-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "five-review-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated five review/context locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
