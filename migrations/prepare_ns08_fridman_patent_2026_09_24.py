"""Prepare the early eCAP artifact electrical-model patent as prior art."""

# ruff: noqa: E501 -- exact claim locators and boundaries are retained.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns08-fridman-us7835804-2010.json"
URL = "https://patents.google.com/patent/US7835804B2/en"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S771":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Gene Yevgeny Fridman; Rankiri Tissa Karunasiri",
            "год": 2010,
            "издание": "United States patent US7835804B2; original assignee Advanced Bionics LLC",
            "модальность": "Electrically evoked compound action potential recording artifact in an implanted neural stimulator",
            "задача": "Model and reduce stimulus-related voltage artifact when measuring an eCAP",
            "метод": "Independent claim 1 defines an eCAP artifact-measurement system with a biphasic current source, stimulation and recording electrodes, coupling capacitors and an amplifier; independent claim 7 recasts the electrical-equivalent model. Dependent claims include electrode-tissue, tissue-impedance and parasitic lead-capacitance components.",
            "датасет": "Electrical-equivalent model and patent drawings; no reported participant cohort or reusable waveform dataset",
            "производительность": None,
            "кросс_субъект": "not_applicable: no patient-level predictive evaluation in the patent claims",
            "релевантность": 3,
            "ограничения": "Earlier apparatus/model prior art for eCAP artifact; claims are not evidence of empirical artifact-removal accuracy, SCS pain benefit or clinical validation. Pulse values in claim 6 are model parameters, not a validated treatment protocol.",
            "тип_источника": "патент",
        }
    )
    record["identifiers"].update({"patent_id": "US7835804B2", "exact_url": URL})
    record["provenance"].update(
        {
            "import_source": "NS-08/NS-13 backward patent snowballing; US patent grant facsimile",
            "retrieved_at": DATE,
            "search_stream": "NS-08/NS-13",
            "query_or_seed": "historical eCAP recording artifact electrical model patent",
            "iteration": 3,
        }
    )
    record["evidence"].update(
        {
            "species": "not_applicable: technology claim, no studied organism cohort",
            "population": "Implantable neural-stimulator/eCAP recording model; no reported clinical cohort",
            "subject_domain": "not_applicable",
            "modalities": ["ecap", "simulation_state"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Modeled post-stimulus voltage artifact at the recording electrode",
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
            "notes": "US grant header and claims 1-12 checked. Claims 1 and 7 are electrical-model/system claims; simulation parameters and apparatus language are not empirical validation.",
        }
    )
    record["risk_flags"] = ["patent_not_empirical_evidence", "ecap_not_pain_measure"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Publication header > Inventors",
        "год": "Publication header > Grant publication date 2010-11-16",
        "издание": "Publication header > Assignee and publication number",
        "модальность": "Abstract; claims 1 and 7",
        "задача": "Abstract; claims 1 and 7",
        "метод": "Claims 1-12, especially independent claims 1 and 7 and dependent claims 3-6",
        "датасет": "Description and claims: electrical-equivalent model without a cohort",
        "производительность": "Claims 1-12: no experimental accuracy estimate",
        "кросс_субъект": "Claims 1-12: no patient-level predictive evaluation",
        "ограничения": "Claims 1, 3-7 and description: model scope only",
        "evidence.species": "Claims 1-12: technology claim without organism cohort",
        "evidence.population": "Abstract and claims 1-12",
        "evidence.sample_size": "Claims 1-12: no clinical sample denominator",
        "evidence.target_construct": "Claim 1: eCAP recording artifact",
        "evidence.target_label": "Claims 1 and 7: voltage artifact",
        "validation.split_unit": "Claims 1-12: no predictive experiment",
        "validation.cross_subject": "Claims 1-12: no subject-level evaluation",
        "validation.external_validation": "Claims 1-12: no independent experiment",
        "validation.calibration": "Claims 1-12: no predictive calibration",
        "validation.uncertainty": "Claims 1-12: no measured uncertainty",
        "validation.notes": "Publication header and claims 1-12",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = (
            "Checked in the published US patent grant; model claims do not establish empirical performance."
        )
        item["locators"] = [{"url": URL, "locator": section}]
    for path, why in {
        "производительность": "No quantified experimental artifact-removal performance is reported.",
        "evidence.sample_size": "No empirical participant cohort is reported in the patent claims.",
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
