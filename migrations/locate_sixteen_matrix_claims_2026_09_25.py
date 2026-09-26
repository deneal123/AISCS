"""Locate sixteen remaining claims and correct open-text access metadata."""

import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S138": (
        "https://www.neuralpress.org/articles/jmn/5/3/dobes-drosophila",
        "Perspective; Abstract, indeterminate valence and four-component audit.",
    ),
    "S330": (
        "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        "Author preprint v2 Abstract, few-shot on-chip seizure detection "
        "and prediction across TUH, EPILEPSIAE, CHB-MIT and Freiburg.",
    ),
    "S045": (
        "https://pubmed.ncbi.nlm.nih.gov/42118625/",
        "Primary article Abstract, 41 participants, thermal-grill "
        "stimuli and self-reported NRS pain labels.",
    ),
    "S023": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11759196/",
        "Abstract; Results 3.1.3, Normalisation and Ratio-Based Feature "
        "Classification: A-to-B 66.6%; reverse B-to-A 59.5%.",
    ),
    "S048": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10704747/",
        "Abstract; Methods, Human median nerve and Nerve FEM; "
        "ESCAPE-NET simulated nCAP source and noise tests.",
    ),
    "S075": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12858468/",
        "Abstract; Selection of Studies; Barriers and Limitations, "
        "real-world implementation and clinical-impact evaluation gaps.",
    ),
    "S084": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13214276/",
        "Abstract; Downstream task performance, Table 5: "
        "significant gains at 6.25% real-data subsampling only.",
    ),
    "S249": (
        "https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2026.1948186/full",
        "Critical narrative review, Abstract and Introduction, "
        "five-stage monitoring-to-outcome decision framework.",
    ),
    "S025": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13400141/",
        "Results, multi-stage cohorts; Figure 1C; Sensitivity of CsPIP "
        "to neuromodulation-induced pain changes, Figure 4; chronic-pain "
        "cohort, Figure 5.",
    ),
    "S042": (
        "https://link.springer.com/article/10.1007/s00586-024-08172-2",
        "Review Abstract, Purpose and Methods: privacy, access and "
        "data-sharing barriers motivating federated learning.",
    ),
    "S083": (
        "https://arxiv.org/abs/2407.19811",
        "Author preprint Abstract, GAN-generated thermal videos, RGB "
        "fusion and BioVid evaluation.",
    ),
    "S165": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12467075/",
        "Abstract; Sections 4 and 5, adaptive neuromodulation in "
        "neurodegenerative rehabilitation and translational constraints.",
    ),
    "S192": (
        "https://arxiv.org/abs/2409.11635",
        "Author preprint Abstract, robotic-patient expressions, "
        "BioVid training/evaluation and robotic integration.",
    ),
    "S244": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12390560/",
        "Methods 2.4; Results 3.1-3.2, Figures 3-4: six-channel "
        "TENS output and synthetic-EMG closed-loop latency.",
    ),
    "S222": (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9807619/",
        "Methods; Results 3.2-3.3, Figures 6 and 11: robot "
        "injury alert and cue-triggered avoidance tasks.",
    ),
    "S252": (
        "https://www.nature.com/articles/s41592-025-02988-6",
        "Editorial body, Method of the Year 2025 selection and "
        "FlyWire context paragraph.",
    ),
}
OPEN_TEXT = {
    "S025": "PMC13400141",
    "S165": "PMC12467075",
    "S244": "PMC12390560",
    "S222": "PMC9807619",
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in records["sources"]}
    for source_id, (url, locator) in LOCATORS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic evidence row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
        if source_id == "S023":
            rows[0]["claim"] = (
                "The study tests EEG markers of later central neuropathic pain "
                "across two independently collected subacute-SCI datasets; "
                "cross-dataset validation was 66.6% from A to B and 59.5% "
                "from B to A."
            )
            rows[0]["limitations"] = (
                "Directional cross-dataset validation is below within-dataset "
                "estimates and has unequal sensitivity; this is prognostic "
                "neuropathic-pain evidence, not momentary pain measurement."
            )
        elif source_id == "S042":
            rows[0]["claim"] = (
                "The review describes privacy, data-access and sharing "
                "barriers that motivate federated learning in spine-surgery research."
            )
        elif source_id == "S075":
            rows[0]["claim"] = (
                "The scoping review maps deep-learning use with noninvasive "
                "sensors and identifies real-world implementation and "
                "clinical-impact evaluation gaps."
            )

    for source_id, pmcid in OPEN_TEXT.items():
        source = sources[source_id]
        if source["evidence"]["access_status"] != "unavailable_after_search":
            raise ValueError(f"Unexpected access status for {source_id}")
        source["evidence"]["access_status"] = "open"
        source["field_resolution"]["evidence.access_status"] = {
            "state": "reported",
            "value": "open",
            "reason": "Official Europe PMC fullTextXML returned HTTP 200 on 2026-09-25.",
            "checked_at": "2026-09-25",
            "locators": [{
                "url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                "locator": "Open full-text XML, article body",
            }],
        }

    s025 = sources["S025"]
    if s025["identifiers"]["pmid"] is not None:
        raise ValueError("S025 PMID is already set")
    if any(
        source["id"] != "S025" and source["identifiers"]["pmid"] == "42309066"
        for source in records["sources"]
    ):
        raise ValueError("S025 PMID collides with another source")
    s025["identifiers"]["pmid"] = "42309066"
    s025["field_resolution"]["identifiers.pmid"] = {
        "state": "reported",
        "value": "42309066",
        "reason": "Official PubMed citation links this PMID to the source DOI.",
        "checked_at": "2026-09-25",
        "locators": [{
            "url": "https://pubmed.ncbi.nlm.nih.gov/42309066/",
            "locator": "Citation, PMID 42309066 and DOI 10.1016/j.xcrm.2026.102793",
        }],
    }

    s023 = sources["S023"]
    old_note = s023["validation"]["notes"]
    if "Cross-dataset validation accuracy was 66.6%" not in old_note:
        raise ValueError("S023 note has changed")
    new_note = old_note.replace(
        "Cross-dataset validation accuracy was 66.6%",
        "Directional cross-dataset validation was 66.6% A-to-B and 59.5% B-to-A",
    )
    s023["validation"]["notes"] = new_note
    for resolution in s023["field_resolution"].values():
        if resolution.get("value") == old_note:
            resolution["value"] = new_note

    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "sixteen_primary_locators_reviewed",
        "access_corrections": OPEN_TEXT,
        "identifier_correction": {"S025": "PMID 42309066"},
        "claim_corrections": {
            "S023": "66.6% A-to-B; 59.5% B-to-A",
            "S042": "Privacy and sharing are barriers motivating FL.",
            "S075": "Gap is real-world and clinical-impact evaluation.",
        },
        "boundaries": (
            "S084 significance was restricted to 6.25% real-data "
            "subsampling. S045 and S042 have publisher abstracts only; "
            "S083 and S192 are author preprint abstracts for proceedings; "
            "S330 full text was blocked, so its abstract alone supports the claim."
        ),
    }
    completeness = json.loads(
        (DATA / "completeness-report.json").read_text(encoding="utf-8")
    )
    completeness.update(completeness_summary(records["sources"]))
    snapshot = snapshot_repository(DATA, label="pre-sixteen-primary-claim-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "completeness-report.json", completeness)
    atomic_write_json(DATA / "sixteen-primary-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated sixteen evidence locators and access metadata; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
