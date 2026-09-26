"""Prepare the primary-reviewed Anaya SCS ECAP forward-model source."""

# ruff: noqa: E501 -- source-method locators and scientific limits are explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns07-anaya-model-2020.json"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC6920600/"
XML_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/PMC6920600/unicode"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S766":
        raise ValueError("Candidate ID changed; inspect before preparing")
    record.update({
        "авторы": "Carlos J. Anaya; Hans J. Zander; Robert D. Graham; Vishwanath Sankarasubramanian; Scott F. Lempka",
        "год": 2020,
        "издание": "Neuromodulation 23(1):64-73; published online 2019-06-19",
        "модальность": "Simulated spinal ECAP and published human ECAP trace comparator",
        "задача": "Explain the neural and physical origins of ECAPs recorded from SCS leads",
        "метод": "Lower-thoracic 3-D finite-element volume conductor in COMSOL, multicompartment dorsal-column sensory axons in NEURON, and reciprocity-based projection of axonal transmembrane currents to inactive lead contacts",
        "датасет": "Literature-based canonical human anatomy and axon-density inputs; one previously published clinical ECAP trace shown as a comparator in Figure 2C, not a new patient cohort",
        "производительность": "At assumed model discomfort threshold, Figure 2C shows clinical and model P2-N1 amplitudes of 200 and 216 microvolts; qualitative N1/P2 morphology and latency agreement, not patient-independent prediction",
        "кросс_субъект": "not_applicable: no patient-level model training or held-out-patient test",
        "релевантность": 5,
        "ограничения": "Canonical literature-based anatomy and lead placement omit interpatient variation. Model sensory threshold is assumed at at least 10% dorsal-column activation and discomfort threshold at 1.4 times this threshold, without established clinical mapping. Dorsal horn neurons are excluded; no new patient-linked pain-outcome validation.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({
        "doi": "10.1111/ner.12965", "pmid": "31215720", "exact_url": URL,
    })
    record["provenance"].update({
        "import_source": "NS-07 PMC author-manuscript BioC full text",
        "retrieved_at": DATE,
        "search_stream": "NS-07",
        "query_or_seed": "Anaya Zander Lempka ECAP computational modeling reciprocity",
        "iteration": 2,
    })
    record["evidence"].update({
        "species": "Homo sapiens (canonical anatomical model)",
        "population": "Literature-derived lower-thoracic anatomy; published human ECAP comparator, no newly enrolled cohort",
        "subject_domain": "simulation",
        "modalities": ["ecap", "simulation_state"],
        "sample_size": None,
        "target_construct": "ecap_neural_recruitment",
        "target_label": "Simulated ECAP P2-N1 amplitude, morphology, conduction velocity and dorsal-column recruitment",
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
        "notes": "Full PMC author manuscript checked via NCBI BioC XML. Figure 2C compares a model ECAP with a previously published clinical trace; this is not a patient-level external test or analgesic response validation.",
    })
    record["risk_flags"] = ["synthetic_only", "ecap_not_pain_measure"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "article byline; authorship statement",
        "год": "citation header: final 2020 issue and online 2019 publication",
        "издание": "citation header",
        "модальность": "Abstract; Materials and Methods; Figure 2C",
        "задача": "Abstract Objectives; Introduction final paragraph",
        "метод": "Materials and Methods > FEM of SCS; Multicompartment cable model of Sensory Axons; Assessment of direct axonal response; Calculation of ECAP recordings",
        "датасет": "Materials and Methods > FEM of SCS; Results > Model-based ECAP recordings, Figure 2C; Study limitations and future work",
        "производительность": "Results > Model-based ECAP recordings, Figure 2C",
        "кросс_субъект": "Materials and Methods and Study limitations: canonical simulation, no patient-level split",
        "ограничения": "Study limitations and future work, all three paragraphs",
        "evidence.species": "Materials and Methods > FEM of SCS: human cadaver-based anatomical dimensions",
        "evidence.population": "Materials and Methods > FEM of SCS; Results > Model-based ECAP recordings, Figure 2C",
        "evidence.sample_size": "Methods and Figure 2C: canonical model and one published clinical trace; no enrolled cohort",
        "evidence.target_construct": "Methods > Calculation of ECAP recordings",
        "evidence.target_label": "Methods > Evaluation of model ECAP recordings",
        "validation.split_unit": "Methods: deterministic anatomical simulation without patient-level split",
        "validation.cross_subject": "Study limitations: interpatient variation not modeled",
        "validation.external_validation": "Results > Figure 2C and Study limitations: published trace comparator only",
        "validation.calibration": "Study limitations and future work",
        "validation.uncertainty": "Study limitations and future work",
        "validation.notes": "Results > Figure 2C; Study limitations and future work",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary author manuscript; the claim is bounded to the cited section."
        item["locators"] = [{"url": XML_URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_applicable", "value": None,
        "reason": "Canonical simulation; a published trace is a comparator, not an enrolled sample.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/31215720/", "locator": "PMID and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
