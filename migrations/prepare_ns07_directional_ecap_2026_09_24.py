"""Prepare the primary-reviewed NS-07 directional-lead ECAP source card."""

# ruff: noqa: E501 -- primary-method details and locators are intentionally explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns07-directional-ecap-2026.json"
URL = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0345287"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S764":
        raise ValueError("Candidate ID changed; inspect before preparing")
    record.update({
        "авторы": "Zhen Wu; Nianshuang Wu; Penghao Wang; Cheng Zhang; Changzhe Wu; Xiaolin Huo; Guanghao Zhang",
        "год": 2026,
        "издание": "PLOS ONE 21(4): e0345287",
        "модальность": "Simulated SCS-induced ECAP waveform, electric field and dorsal-column fiber recruitment",
        "задача": "Model ECAP recording and fiber recruitment for directional versus traditional percutaneous SCS leads",
        "метод": "Eight-layer human thoracic volume conductor in COMSOL, multicompartment sensory fibers in NEURON, reciprocity-based ECAP calculation at recording contacts",
        "датасет": "Literature-based anatomical and conductivity parameters; model output and files deposited at Figshare DOI 10.6084/m9.figshare.29558654",
        "производительность": "Simulated E3-E0 ECAP amplitude at 8 mA: 244.8 microvolts for traditional lead and 363.6 microvolts for directional lead; model comparison, not clinical efficacy",
        "кросс_субъект": "not_applicable",
        "релевантность": 5,
        "ограничения": "Computational model only; no enrolled patient cohort or independent clinical-outcome validation. Dorsal-column fibers were simplified into 26 superficial regions; dorsal-root recruitment, CSF motion and postural lead displacement were not modeled. ECAP is not pain intensity.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({
        "doi": "10.1371/journal.pone.0345287", "pmid": "41926484", "exact_url": URL,
    })
    record["provenance"].update({
        "import_source": "NS-07 primary publisher full-text search",
        "retrieved_at": DATE,
        "search_stream": "NS-07",
        "query_or_seed": "spinal cord stimulation ECAP computational model volume conductor extracellular potential",
        "iteration": 1,
    })
    record["evidence"].update({
        "species": "Homo sapiens (anatomical model)",
        "population": "Simulated human thoracic spinal cord and epidural electrode leads; no enrolled subjects",
        "subject_domain": "simulation",
        "modalities": ["ecap", "simulation_state"],
        "sample_size": None,
        "target_construct": "ecap_neural_recruitment",
        "target_label": "Simulated ECAP amplitude and waveform; activated dorsal-column fiber fraction",
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
        "notes": "Publisher full text Methods and Limitations checked. The paper models a physical ECAP measurement operator and directional lead geometry; it has no Drosophila component or patient-linked SCS outcome.",
    })
    record["risk_flags"] = [
        "synthetic_only", "ecap_not_pain_measure", "future_or_recent_record_requires_recheck",
    ]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "article byline",
        "год": "publication date",
        "издание": "citation line",
        "модальность": "Abstract; Methods > Calculation of simulated ECAP signals",
        "задача": "Introduction, last two paragraphs",
        "метод": "Methods > Simulation model of SCS-induced electric field; Multi-compartment cable model; Calculation of simulated ECAP signals",
        "датасет": "Data Availability; Methods > Simulation model of SCS-induced electric field",
        "производительность": "Discussion, simulated E3-E0 comparison at 8 mA",
        "кросс_субъект": "Methods: simulation without participant cohort",
        "ограничения": "Limitations, paragraphs 1-3",
        "evidence.species": "Methods > Simulation model of SCS-induced electric field",
        "evidence.population": "Methods > Simulation model of SCS-induced electric field",
        "evidence.sample_size": "Methods: simulation without participant cohort",
        "evidence.target_construct": "Methods > Calculation of simulated ECAP signals",
        "evidence.target_label": "Methods > Calculation of simulated ECAP signals",
        "validation.split_unit": "Methods: simulation without participant cohort",
        "validation.cross_subject": "Methods: simulation without participant cohort",
        "validation.external_validation": "Methods and Limitations: no independent patient outcome test",
        "validation.calibration": "Methods and Limitations",
        "validation.uncertainty": "Methods and Limitations",
        "validation.notes": "Methods and Limitations",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary publisher full text; the stated boundary is explicit in the cited section."
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_applicable",
        "value": None,
        "reason": "This is a computational anatomical model with no enrolled participants.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/41926484/", "locator": "PMID 41926484 and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
