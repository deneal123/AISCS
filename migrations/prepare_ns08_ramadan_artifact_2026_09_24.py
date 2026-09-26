"""Prepare a publisher-verified NS-08 SCS artifact-removal source card."""

# ruff: noqa: E501 -- primary locators are intentionally explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns08-ramadan-artifact-2023.json"
URL = "https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1072786/full"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S765":
        raise ValueError("Candidate ID changed; inspect before preparing")
    record.update({
        "авторы": "Ahmed Ramadan; Seth D. König; Mingming Zhang; Erika K. Ross; Alexander Herman; Théoden I. Netoff; David P. Darrow",
        "год": 2023,
        "издание": "Frontiers in Pain Research 4:1072786",
        "модальность": "Human epidural SCS recordings and ECAP signal processing",
        "задача": "Assess hardware settings and artifact-removal fits for ECAP measurement during SCS",
        "метод": "Two trial patients with externalized leads; fit single exponential, double exponential and second-order polynomial to averaged recordings at 0.375-4 ms after stimulation, then subtract each fit and compare ECAP N1 timing, P2-N1 amplitude and fit computation time",
        "датасет": "Two participants, 20 observations across visits and stimulation parameters; one observation is one or more concatenated trials, not an independent participant",
        "производительность": "Double exponential fit gave the best artifact fit; second-order polynomial gave similar ECAP N1 timing and P2-N1 amplitude with shorter computation time in the tested recordings",
        "кросс_субъект": "no: methods comparison used repeated recordings from two participants",
        "релевантность": 5,
        "ограничения": "Technical ECAP extraction from only two patients; no independent held-out-patient evaluation or clinical pain-outcome prediction. The authors caution that curve fitting may overestimate or underestimate neural response and that averaging opposite polarities can distort ECAP morphology.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({
        "doi": "10.3389/fpain.2023.1072786", "exact_url": URL,
    })
    record["provenance"].update({
        "import_source": "NS-08 primary publisher full-text search",
        "retrieved_at": DATE,
        "search_stream": "NS-08",
        "query_or_seed": "spinal cord stimulation ECAP artifact removal exponential polynomial",
        "iteration": 1,
    })
    record["evidence"].update({
        "species": "Homo sapiens",
        "population": "Two chronic-pain SCS trial participants with externalized percutaneous leads",
        "subject_domain": "human_clinical",
        "modalities": ["ecap"],
        "sample_size": "2 participants; 20 repeated observations across visits and settings",
        "target_construct": "technical_signal_quality",
        "target_label": "Stimulation artifact fit and ECAP N1 timing/P2-N1 amplitude",
        "access_status": "open",
        "evidence_role": "method_baseline",
    })
    record["validation"].update({
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "recording",
        "cross_subject": "no",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "exclusion_reason": None,
        "notes": "Publisher Methods, Results and Discussion checked. The 20 observations are repeated measurements of two people. This establishes artifact-fit prior art, not clinical outcome validity.",
    })
    record["risk_flags"] = ["ecap_not_pain_measure", "missing_cross_subject_validation"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "article byline",
        "год": "publication date",
        "издание": "citation line",
        "модальность": "Abstract; Methods 3.3-3.4",
        "задача": "Introduction, final paragraph; Abstract Objectives",
        "метод": "Methods 3.4.3 Artifact removal; 3.4.4 ECAP metrics; 3.4.5 Statistics",
        "датасет": "Methods 3.1 Participants; 3.4.5 Statistics and Table 3",
        "производительность": "Results 4.1.1 Artifact removal, Figure 5; Discussion 5.3",
        "кросс_субъект": "Methods 3.1 and 3.4.5: two people and repeated observations",
        "ограничения": "Methods 3.1, 3.4.5; Discussion 5.3 paragraphs on fit bias and polarity",
        "evidence.species": "Methods 3.1 Participants",
        "evidence.population": "Methods 3.1 Participants",
        "evidence.sample_size": "Methods 3.1 and 3.4.5, Table 3",
        "evidence.target_construct": "Methods 3.4.3-3.4.4",
        "evidence.target_label": "Methods 3.4.4 ECAP metrics",
        "validation.split_unit": "Methods 3.4.5 Statistics: definition of an observation",
        "validation.cross_subject": "Methods 3.1 and 3.4.5: two people; no held-out participant",
        "validation.external_validation": "Methods and Results: technical comparison within two participants",
        "validation.calibration": "Methods and Results: no calibration assessment",
        "validation.uncertainty": "Methods and Results: no predictive uncertainty assessment",
        "validation.notes": "Methods, Results and Discussion 5.3",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary publisher full text; boundaries follow the cited section."
        item["locators"] = [{"url": URL, "locator": section}]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
