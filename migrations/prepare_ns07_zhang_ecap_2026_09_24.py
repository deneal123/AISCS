"""Prepare the primary-reviewed Zhang spinal ECAP simulation source."""

# ruff: noqa: E501 -- retain precise full-text section locators.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns07-zhang-ecap-model-2021.json"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9927682/"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S768":
        raise ValueError("Candidate ID changed; inspect before preparing")
    record.update({
        "авторы": "Guanghao Zhang; Cheng Zhang; Changzhe Wu; Xiaolin Huo",
        "год": 2021,
        "издание": "Journal of Biomedical Engineering 38(2):232-240; article in Chinese with English abstract",
        "модальность": "Simulated SCS field, dorsal-column sensory fibers and differential ECAP waveform",
        "задача": "Relate simulated ECAP waveform components to the degree of dorsal-column fiber recruitment",
        "метод": "T10-centered ANSYS volume-conductor model with 26 superficial white-matter regions, NEURON multicompartment sensory fibers, 210-microsecond stimulation and reciprocity-based calculation of differential single-fiber potentials summed into ECAP",
        "датасет": "Literature-derived human spinal geometry and conductivities; no newly enrolled participants or patient-level ECAP dataset",
        "производительность": "In simulations, no more than 10% dorsal-column fiber activation yielded peaks associated with large fibers, while activation of at least 20% produced a slow-conduction peak associated with smaller fibers",
        "кросс_субъект": "not_applicable: computational simulation without a patient cohort",
        "релевантность": 5,
        "ограничения": "Simulation only. The 15-volunteer MRI geometry cited in Methods came from an earlier study, not a participant cohort in this ECAP experiment. Fiber paths and density are simplified to superficial regions; no independent clinical ECAP or pain-outcome validation is reported.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({
        "doi": "10.7507/1001-5515.202007016", "pmid": "33913282", "exact_url": URL,
    })
    record["provenance"].update({
        "import_source": "NS-07 primary journal full text via PMC",
        "retrieved_at": DATE,
        "search_stream": "NS-07",
        "query_or_seed": "Anaya ECAP simulation forward citation Zhang 2021",
        "iteration": 3,
    })
    record["evidence"].update({
        "species": "Homo sapiens (literature-derived anatomical model)",
        "population": "Computational T10 spinal model; no recruited study participants",
        "subject_domain": "simulation",
        "modalities": ["ecap", "simulation_state"],
        "sample_size": None,
        "target_construct": "ecap_neural_recruitment",
        "target_label": "Simulated ECAP waveform peaks and activated dorsal-column fiber fraction",
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
        "notes": "The primary Chinese journal full text and English abstract were checked. Simulated activation fractions are model outputs, not observed human neural counts or pain outcomes.",
    })
    record["risk_flags"] = ["synthetic_only", "ecap_not_pain_measure"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "article byline",
        "год": "citation header, 2021-04-25",
        "издание": "citation header and language statement",
        "модальность": "Abstract; sections 1.1-1.4",
        "задача": "Abstract; Introduction final paragraph",
        "метод": "sections 1.1 volume conductor, 1.2 multicompartment fibers, 1.3 SFAP, 1.4 ECAP synthesis; Figures 1-4",
        "датасет": "section 1.1: anatomical parameters cited from 15-volunteer MRI study; no current enrolled cohort",
        "производительность": "English Abstract; section 2 Results",
        "кросс_субъект": "sections 1-2: computational model only",
        "ограничения": "sections 1.1-1.4 and Discussion: simplified superficial fiber model and no clinical validation",
        "evidence.species": "section 1.1: literature-derived human T10 geometry",
        "evidence.population": "section 1.1: no current participant cohort",
        "evidence.sample_size": "section 1.1: earlier MRI cohort supplies parameters, not study sample",
        "evidence.target_construct": "sections 1.3-1.4, differential SFAP and summed ECAP",
        "evidence.target_label": "English Abstract; section 2 Results",
        "validation.split_unit": "sections 1-2: simulation, no participant split",
        "validation.cross_subject": "sections 1-2: simulation, no cross-subject test",
        "validation.external_validation": "sections 1-2: no independent clinical test",
        "validation.calibration": "sections 1-2: no clinical calibration assessment",
        "validation.uncertainty": "sections 1-2: no predictive uncertainty assessment",
        "validation.notes": "English Abstract; sections 1.1-1.4 and Results",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary journal text; simulation and human evidence are distinguished."
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_applicable", "value": None,
        "reason": "No participants were enrolled in this computational study.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/33913282/", "locator": "PMID and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
