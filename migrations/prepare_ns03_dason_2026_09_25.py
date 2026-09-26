"""Prepare Dason et al. from the PNAS primary article for NS-03."""

# ruff: noqa: E501 -- preserve exact article and figure locators.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns03-dason-2020.json"
URL = "https://www.pnas.org/doi/10.1073/pnas.1820840116"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S777":
        raise ValueError("Unexpected candidate ID")
    record.update({
        "авторы": "Jeffrey S. Dason; Amanda Cheung; Ina Anreiter; Vanessa A. Montemurri; Aaron M. Allen; Marla B. Sokolowski",
        "год": 2020,
        "издание": "Proceedings of the National Academy of Sciences 117(38):23286-23291; online 18 June 2019",
        "модальность": "Larval 42 C thermal-probe and pr1 optogenetic escape assays; CNS expression imaging, qRT-PCR and activity-dependent GRASP",
        "задача": "Test the foraging gene and pr1 ventral-nerve-cord cells in genetically and developmentally variable larval escape",
        "метод": "Rover, sitter and for-null genotype comparisons; pr1 rescue and RNAi; red-light Chrimson activation with GAL80 intersection; thermal rolling latency; activity-dependent GRASP at cIV/pr1 contacts",
        "датасет": "Drosophila melanogaster larvae across 48-120 h after egg laying; per-genotype and per-assay sample sizes in Figures 1-4",
        "производительность": "Figure 2C: thermal response-latency comparison used 126 sitters, 58 rovers and 123 for-null larvae; Figure 4C: pr1 activation at 103-119 h increased latency at 120 h (P<0.0001; n=134-168 per group)",
        "кросс_субъект": "not_applicable: no subject-level predictive model",
        "релевантность": 4,
        "ограничения": "GRASP supports a candidate active synaptic contact but is not an EM connectome or a measured human spinal response. Rolling and curling are protective larval actions, not subjective pain. Developmental stimulation changes behavior in separate larvae; no human ECAP, SCS outcome or cross-species validation.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({"doi": "10.1073/pnas.1820840116", "pmid": "31213548", "exact_url": URL})
    record["provenance"].update({
        "import_source": "NS-03 backward-citation primary PNAS article",
        "retrieved_at": DATE, "search_stream": "NS-03",
        "query_or_seed": "S212/S282 backward citations; Dason foraging nociception",
        "iteration": 4,
    })
    record["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": "First-, second- and third-instar larvae in developmental assays; thermal outcomes assessed at 120 h after egg laying",
        "subject_domain": "drosophila_larva",
        "modalities": ["behavior"],
        "sample_size": None, "target_construct": "nociceptive_response",
        "target_label": "Curling and rolling response and latency to a 42 C probe or pr1-cell optogenetic activation",
        "access_status": "open", "evidence_role": "simulation_foundation",
    })
    record["validation"].update({
        "status": "verified_primary", "screening_status": "included_core",
        "full_text_status": "checked", "checked_at": DATE,
        "split_unit": "not_applicable", "cross_subject": "not_applicable",
        "external_validation": "not_applicable", "calibration": "not_applicable",
        "uncertainty": "not_reported", "exclusion_reason": None,
        "notes": "PNAS full text checked; 2019 online date and 2020 issue date distinguished. GRASP and gene-expression results are separate from behavioral latency; no pain or clinical transfer claim.",
    })
    record["relations"] = []
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "авторы": "Article byline",
        "год": "Article header: 18 June 2019 online; issue 22 September 2020, volume 117(38)",
        "издание": "Article citation: PNAS 117(38):23286-23291",
        "модальность": "Abstract; Results, Figures 1-4; Materials and Methods",
        "задача": "Abstract and Significance",
        "метод": "Results, Figures 2-4; Materials and Methods",
        "датасет": "Results, Figure 4A and legend: 48-120 h AEL; Figure 2C and legend: genotype counts",
        "производительность": "Results, Figures 2C and 4C and legends",
        "кросс_субъект": "Methods: larval perturbation experiments without prediction model",
        "ограничения": "Abstract; Results, Figures 2-4; Discussion",
        "evidence.species": "Article title and Abstract",
        "evidence.population": "Results, Figure 4A-C: larval stages and thermal-test age",
        "evidence.sample_size": "Figures 1-4 give assay-specific n; no single whole-study n",
        "evidence.target_construct": "Abstract; Results, pr1 neurons and thermal nociception",
        "evidence.target_label": "Results, Figures 2B-C and 4B-E",
        "validation.split_unit": "Methods: no trained patient/animal prediction model",
        "validation.cross_subject": "Methods: Drosophila larvae only",
        "validation.external_validation": "Methods: no independent prediction test",
        "validation.calibration": "Methods: no probabilistic prediction model",
        "validation.uncertainty": "Figures report group SEM and tests, not model uncertainty",
        "validation.notes": "Article header; Results, Figures 1-4; Discussion",
    }
    for path, locator in locators.items():
        field = record["field_resolution"][path]
        field["reason"] = "Checked in the primary PNAS article; neural and behavioral measurements remain distinct."
        field["locators"] = [{"url": URL, "locator": locator}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_reported", "value": None,
        "reason": "Assay-specific denominators are reported in figures; a single whole-study count is not.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/31213548/", "locator": "PMID; 2020 issue and 2019 Epub dates"}
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
