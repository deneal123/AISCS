"""Prepare the Tracey 2003 larval nociception study from archived publisher text."""

# ruff: noqa: E501 -- retain exact publisher figure and methods locators.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns03-tracey-2003.json"
PUBLISHER = "https://www.cell.com/cell/fulltext/S0092-8674(03)00272-1"
ARCHIVE = "https://web.archive.org/web/20230522064658/https://www.cell.com/cell/fulltext/S0092-8674(03)00272-1"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S778":
        raise ValueError("Unexpected candidate ID")
    record.update({
        "авторы": "W. Daniel Tracey Jr.; Rachel I. Wilson; Gilles Laurent; Seymour Benzer",
        "год": 2003,
        "издание": "Cell 113(2):261-273",
        "модальность": "Larval heated-probe and mechanical behavioral assays, multidendritic-neuron genetic silencing, nerve electrophysiology and painless mutant/rescue tests",
        "задача": "Identify a gene and peripheral neurons required for thermal and mechanical nociceptive escape in Drosophila larvae",
        "метод": "Heated probe rolling assay and EP-element mutant screen; multidendritic GAL4/TeTxLC silencing; larval nerve recordings; painless gene rescue and expression localization",
        "датасет": "Drosophila melanogaster larvae; experiment-specific animal and nerve counts in figures, without one whole-study denominator",
        "производительность": "Results, Figure 2E: a 45 mN mechanical filament evoked rolling in 92% of wild-type larvae (n=36) versus 13% of painless1 mutants (n=31); Figure 3: wild-type nerve firing increased above about 38 C, absent in painless mutants",
        "кросс_субъект": "not_applicable: no subject-level predictive model",
        "релевантность": 4,
        "ограничения": "Peripheral nerve firing and protective larval rolling are different observables; neither directly measures subjective pain. Genetic silencing does not exclude untargeted neurons. No central connectome, human ECAP, SCS outcome or cross-species validation is provided. The live publisher route was inaccessible here; an archived publisher full-text page was checked.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({"doi": "10.1016/S0092-8674(03)00272-1", "pmid": "12705873", "exact_url": PUBLISHER})
    record["provenance"].update({
        "import_source": "NS-03 backward-citation publisher article via Internet Archive snapshot",
        "retrieved_at": DATE, "search_stream": "NS-03",
        "query_or_seed": "S212/S282 backward citations; Tracey 2003 painless",
        "iteration": 4,
    })
    record["evidence"].update({
        "species": "Drosophila melanogaster", "population": "Larvae in genetic, heat-probe and nerve-recording assays",
        "subject_domain": "drosophila_larva", "modalities": ["neural_activity", "behavior"],
        "sample_size": None, "target_construct": "nociceptive_response",
        "target_label": "Rolling response to noxious heat or mechanical stimulation and heat-evoked peripheral nerve activity",
        "access_status": "restricted", "evidence_role": "simulation_foundation",
    })
    record["validation"].update({
        "status": "verified_primary", "screening_status": "included_core",
        "full_text_status": "checked", "checked_at": DATE,
        "split_unit": "not_applicable", "cross_subject": "not_applicable",
        "external_validation": "not_applicable", "calibration": "not_applicable",
        "uncertainty": "not_reported", "exclusion_reason": None,
        "notes": "Archived copy of the original Cell publisher full text checked on 25 September 2026 (HTTP 200, article figures and methods present); live publisher route blocked in this environment. No subjective-pain or human-transfer claim.",
    })
    record["relations"] = []
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "авторы": "Publisher article byline",
        "год": "Publisher article citation, 2003",
        "издание": "Publisher article citation, Cell 113(2):261-273",
        "модальность": "Results, Figures 1-3 and 5; Experimental Procedures",
        "задача": "Summary and Introduction",
        "метод": "Results, Figures 1-3 and 5; Experimental Procedures",
        "датасет": "Results, figure legends give separate assay counts",
        "производительность": "Results, Figure 2E (45 mN mechanical rolling) and Figure 3 (nerve firing)",
        "кросс_субъект": "Experimental Procedures: fly assays, no predictive model",
        "ограничения": "Results, Figures 1-3; Discussion",
        "evidence.species": "Summary and Experimental Procedures",
        "evidence.population": "Results, larval rolling and nerve preparations",
        "evidence.sample_size": "Figure legends: experiment-specific n, no whole-study total",
        "evidence.target_construct": "Summary and Results, thermal and mechanical nociception",
        "evidence.target_label": "Results, Figures 1 and 3",
        "validation.split_unit": "Experimental Procedures: no trained prediction model",
        "validation.cross_subject": "Experimental Procedures: larvae only",
        "validation.external_validation": "Results and Methods: no external prediction test",
        "validation.calibration": "Methods: no probabilistic predictive model",
        "validation.uncertainty": "Figure legends give experiment counts, not model uncertainty",
        "validation.notes": "Archived publisher article, Summary; Results, Figures 1-3 and 5; Experimental Procedures",
    }
    for path, locator in locators.items():
        field = record["field_resolution"][path]
        field["reason"] = "Checked in an archived copy of the original publisher full text; original figure and section numbers retained."
        field["locators"] = [{"url": ARCHIVE, "locator": locator}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_reported", "value": None,
        "reason": "The paper reports per-experiment counts but no single whole-study denominator.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/12705873/", "locator": "PMID, DOI and citation"}
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
