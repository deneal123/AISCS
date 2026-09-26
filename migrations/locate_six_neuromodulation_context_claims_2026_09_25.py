"""Pin six contextual claims to primary article and project sections."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S049": (
        "https://pubmed.ncbi.nlm.nih.gov/36792646/",
        "Abstract, study sample and ECAP classifier; Figure 5, "
        "STN-versus-dorsal electrode classification in four primates.",
    ),
    "S021": (
        "https://pubmed.ncbi.nlm.nih.gov/21096375/",
        "Abstract, dorsal-horn spike detection, mechanical stimuli "
        "and wireless neurostimulator feedback loop.",
    ),
    "S097": (
        "https://www.mdpi.com/1424-8220/26/4/1275",
        "Abstract; Introduction, survey structure and threat, defense "
        "and benchmark-gap taxonomy.",
    ),
    "S246": (
        "https://cordis.europa.eu/project/id/101070908/reporting",
        "Periodic Reporting for period 2, objectives, work performed "
        "and progress beyond the state of the art.",
    ),
    "S095": (
        "https://www.ipipublishing.org/index.php/ipil/article/view/361",
        "News and Views article type; Abstract; References 1-6, "
        "FlyWire, Shiu model and Eon embodied-fly narrative.",
    ),
    "S247": (
        "https://arxiv.org/abs/2512.01133v2",
        "Author preprint v2, Abstract, mathematical model and "
        "180 nm CMOS implementation results.",
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
            raise ValueError(f"Expected one generic evidence row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "primary_abstract_or_section_located",
        "boundary": (
            "S049 concerns Parkinsonian STN DBS in four nonhuman primates, "
            "not spinal-cord stimulation or pain. S021 is an animal dorsal-horn "
            "prototype, not clinical efficacy. S097 is a survey; S246 is an "
            "EU project report with in-vitro results; S095 is commentary; "
            "S247 is a silicon circuit, not a biological neuron recording."
        ),
        "access_note": (
            "S021 and S049 are anchored to primary PubMed abstracts; "
            "S247 to the author version-specific arXiv abstract. "
            "Full-method claims are not inferred from these abstracts."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-six-neuromodulation-context-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "six-neuromodulation-context-locator-review-2026-09-25.json", audit)
    print(f"Updated six contextual evidence locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
