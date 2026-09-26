"""Prepare the early cochlear ECAP artifact-removal patent as bounded prior art."""

# ruff: noqa: E501 -- patent claim locators and scientific boundaries need full text.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns08-strahl-wo2010032132-2010.json"
URL = "https://patents.google.com/patent/WO2010032132A1/en"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S770":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Stefan Strahl",
            "год": 2010,
            "издание": "WIPO PCT publication WO2010032132A1; applicant MED-EL Elektromedizinische Geraete GmbH",
            "модальность": "Stimulus-contaminated neuronal waveform and evoked compound action potential, exemplified by cochlear implant recordings",
            "задача": "Derive a stimulus and separate its artifact from neuronal action-potential recordings",
            "метод": "Claim 1 derives an electrical stimulus using a cost-function comparison with known neuronal action-potential waveforms; dependent claim 7 applies a source-separation algorithm after recording. Claims 2-3 specify ECAP and a cochlear implant.",
            "датасет": "Patent disclosure and waveform examples; no identified human cohort or reusable signal dataset",
            "производительность": None,
            "кросс_субъект": "not_applicable: patent does not report a predictive cross-subject experiment",
            "релевантность": 3,
            "ограничения": "Patent method claims establish earlier ECAP artifact-removal prior art, primarily in cochlear stimulation. No SCS-specific experiment, independent clinical validation, participant denominator, or quantified performance is established by the claims.",
            "тип_источника": "патент",
        }
    )
    record["identifiers"].update({"patent_id": "WO2010032132A1", "exact_url": URL})
    record["provenance"].update(
        {
            "import_source": "NS-08/NS-13 backward patent snowballing; WO publication facsimile",
            "retrieved_at": DATE,
            "search_stream": "NS-08/NS-13",
            "query_or_seed": "historical ECAP stimulus artifact removal patent",
            "iteration": 3,
        }
    )
    record["evidence"].update(
        {
            "species": "not_applicable: technology claim, no studied organism cohort",
            "population": "Claimed neural-stimulator waveforms, with cochlear implants as the worked example",
            "subject_domain": "not_applicable",
            "modalities": ["ecap"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Neuronal action potential after stimulus-artifact separation",
            "access_status": "open",
            "evidence_role": "context_only",
        }
    )
    record["validation"].update(
        {
            "status": "verified_primary",
            "screening_status": "included_context",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": "WO publication header, description paragraphs [0001]-[0011], and claims 1-7 checked. Patent claim scope is not empirical validation; cochlear example is not SCS.",
        }
    )
    record["risk_flags"] = ["patent_not_empirical_evidence", "ecap_not_pain_measure"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Publication header > Inventor: Stefan Strahl",
        "год": "Publication header > Publication date 2010-03-25",
        "издание": "Publication header > Applicant and publication number",
        "модальность": "Description [0002]-[0005]; claims 2-3",
        "задача": "Abstract; description [0006]-[0011]",
        "метод": "Claims 1-7, especially claims 1, 2, 3 and 7",
        "датасет": "Description [0001]-[0023]: examples but no cohort or public dataset",
        "производительность": "Claims 1-7 and description [0001]-[0023]: no validated performance estimate",
        "кросс_субъект": "Claims 1-7: no cross-subject study",
        "ограничения": "Description [0002] and claims 1-7",
        "evidence.species": "Claims 1-7: technology claim without organism cohort",
        "evidence.population": "Description [0002]-[0005]; claims 2-3",
        "evidence.sample_size": "Claims 1-7 and description: no empirical denominator",
        "evidence.target_construct": "Claim 7: artifact separation",
        "evidence.target_label": "Claim 7: neuronal action potentials remaining after source separation",
        "validation.split_unit": "Claims 1-7: no predictive experiment",
        "validation.cross_subject": "Claims 1-7: no subject-level evaluation",
        "validation.external_validation": "Claims 1-7: no independent experiment",
        "validation.calibration": "Claims 1-7: no predictive calibration",
        "validation.uncertainty": "Claims 1-7: no measured uncertainty",
        "validation.notes": "Publication header; description [0001]-[0011]; claims 1-7",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = (
            "Checked in the published WO patent document; claims do not establish empirical performance."
        )
        item["locators"] = [{"url": URL, "locator": section}]
    for path, why in {
        "производительность": "No quantified experimental performance is reported in the patent claims or description.",
        "evidence.sample_size": "No empirical participant cohort is reported in this patent disclosure.",
    }.items():
        record["field_resolution"][path].update(
            {
                "state": "not_reported",
                "value": None,
                "reason": why,
            }
        )
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
