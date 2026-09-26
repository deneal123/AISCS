"""Prepare a primary-reviewed human ECAP recruitment-estimation analogue."""

# ruff: noqa: E501 -- retain full primary locators and study boundaries.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns09-brucker-hahn-2023.json"
URL = "https://iopscience.iop.org/article/10.1088/1741-2552/aceca4/pdf"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S767":
        raise ValueError("Candidate ID changed; inspect before preparing")
    record.update({
        "авторы": "Meagan K. Brucker-Hahn; Hans J. Zander; Andrew J. Will; Jayesh C. Vallabh; Jason S. Wolff; David A. Dinsmoor; Scott F. Lempka",
        "год": 2023,
        "издание": "Journal of Neural Engineering 20(4):046028",
        "модальность": "Human spinal ECAP recordings plus computational dorsal-column recruitment model",
        "задача": "Measure how posture and pulse width alter spinal ECAP features and test whether constant ECAP amplitude implies constant neural recruitment",
        "метод": "Acute externalized SCS-trial ECAP growth-curve sweeps across postures and 90-300 microsecond pulse widths; artifact model and growth-curve estimation; FEM and 10,000 dorsal-column axons with reciprocity-based ECAP simulation across dorsal CSF thicknesses",
        "датасет": "56 trial participants and 479 trials; 195 trials excluded from growth-curve fitting; analyzed 284 datasets from 45 participants. Human recordings are commercially sensitive and available only upon reasonable request, not public download.",
        "производительность": "Experimental supine versus seated ECAP threshold was 65.7% lower and growth rate 178.5% higher; in the model a fixed 25 microvolt ECAP required 94% more activated axons at 4.4 mm versus 2.0 mm dorsal CSF thickness",
        "кросс_субъект": "not_applicable: descriptive repeated-measure analysis, no held-out participant predictive model",
        "релевантность": 5,
        "ограничения": "Acute trial-phase recordings only; 11 of 56 participants had all growth-curve trials excluded. Model lacked stimulation artifact and biological noise, used averaged anatomy, and did not predict patient-linked analgesic outcomes. Constant ECAP amplitude failed to guarantee constant recruitment in simulation.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({
        "doi": "10.1088/1741-2552/aceca4", "pmid": "37531954", "exact_url": URL,
    })
    record["provenance"].update({
        "import_source": "NS-09 primary publisher PDF",
        "retrieved_at": DATE,
        "search_stream": "NS-09",
        "query_or_seed": "ECAP posture pulse width constant amplitude neural recruitment Brucker-Hahn",
        "iteration": 3,
    })
    record["evidence"].update({
        "species": "Homo sapiens",
        "population": "56 people undergoing commercial SCS trials; growth-curve analysis retained 45 people",
        "subject_domain": "human_clinical",
        "modalities": ["ecap", "simulation_state"],
        "sample_size": "56 participants, 479 trials; 284 analyzed growth curves from 45 participants",
        "target_construct": "ecap_neural_recruitment",
        "target_label": "ECAP threshold, growth rate and modeled activated axon count across posture/CSF distance",
        "access_status": "open",
        "evidence_role": "method_baseline",
    })
    record["validation"].update({
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "not_applicable",
        "cross_subject": "not_applicable",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "exclusion_reason": None,
        "notes": "Publisher PDF sections 2-4 and data statement checked. Human ECAP feature variation and model-derived axon count are distinct evidence; no clinical pain-response prediction was tested.",
    })
    record["risk_flags"] = ["ecap_not_pain_measure", "missing_cross_subject_validation"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "p. 1, byline",
        "год": "p. 1, citation and publication date",
        "издание": "p. 1, citation",
        "модальность": "Abstract; sections 2.1-2.3",
        "задача": "Abstract Objective; Introduction final two paragraphs",
        "метод": "sections 2.1-2.3, Figure 1 and Figure 2; Appendix growth-curve fitting",
        "датасет": "section 3 Results opening paragraph; section 5 Data availability statement",
        "производительность": "Abstract Main results; section 3.3; section 4.3, Figure 8",
        "кросс_субъект": "sections 2.1 and 3: repeated descriptive trials, no prediction split",
        "ограничения": "section 3 opening paragraph; section 4.4 Study limitations and future work",
        "evidence.species": "section 2.1 Experimental data acquisition",
        "evidence.population": "section 2.1; section 3 opening paragraph",
        "evidence.sample_size": "section 3 opening paragraph: 479, 195, 284 and 45 denominators",
        "evidence.target_construct": "sections 2.2-2.3; Figure 8",
        "evidence.target_label": "sections 2.2-2.3; Figure 8",
        "validation.split_unit": "section 2.1 and section 3: descriptive analysis, no train/test split",
        "validation.cross_subject": "section 2.1 and section 3: repeated recordings, no held-out test",
        "validation.external_validation": "section 4.4: acute trial cohort and generalized model",
        "validation.calibration": "sections 3-4: no predictive calibration test",
        "validation.uncertainty": "sections 3-4: no predictive uncertainty test",
        "validation.notes": "section 4.4 Study limitations and future work",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the publisher PDF; experimental and simulated findings are separated."
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/37531954/", "locator": "PMID and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
