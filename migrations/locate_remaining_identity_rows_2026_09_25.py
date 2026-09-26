"""Replace five remaining generic bibliography identity locators."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S243": (
        "https://clinicaltrials.gov/api/v2/studies/NCT04662905",
        "Official study JSON, protocolSection.identificationModule: "
        "NCT04662905, ECAP-controlled closed-loop SCS for chronic pain.",
    ),
    "S033": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11920397/",
        "PMC article citation: Gopal et al., Scientific Reports 2025;15:9279; "
        "DOI 10.1038/s41598-025-92111-8; PMCID PMC11920397.",
    ),
    "S289": (
        "https://patents.google.com/patent/US20220323766A1/en",
        "Patent publication cover, Info: publication number US20220323766A1, "
        "title and publication date 2022-10-13.",
    ),
    "S016": (
        "https://api.crossref.org/works/10.3390%2Fs25041150",
        "Crossref message.DOI and title: multimodal intraoperative "
        "EEG/PPG/ECG nociception monitoring article.",
    ),
    "S195": (
        "https://pubmed.ncbi.nlm.nih.gov/42732075/",
        "PubMed citation: Yang et al., Journal of Translational Medicine "
        "2026;24:1177, DOI 10.1186/s12967-026-08529-9, PMID 42732075.",
    ),
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    for source_id, (url, locator) in LOCATORS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["claim"] == "The bibliographic source exists under the verified identifier."
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic identity row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "five_identity_locators_reviewed",
        "boundary": "Official study, article and DOI records and the patent publication "
        "cover establish identity only. They do not establish study methods or outcomes.",
    }
    snapshot = snapshot_repository(DATA, label="pre-remaining-identity-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "remaining-identity-locator-review-2026-09-25.json", audit)
    print(f"Updated five remaining identity locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
