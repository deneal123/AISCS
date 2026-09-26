"""Prepare Ohyama 2013 from the primary PLOS article for NS-03."""

# ruff: noqa: E501 -- preserve primary section and figure locators.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns03-ohyama-2013.json"
URL = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0071706"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S776":
        raise ValueError("Unexpected candidate ID")
    record.update({
        "авторы": "Tomoko Ohyama; Tihana Jovanic; Gennady Denisov; Tam C. Dang; Dominik Hoffmann; Rex A. Kerr; Marta Zlatic",
        "год": 2013,
        "издание": "PLOS ONE 8(8):e71706",
        "модальность": "Timed noxious heat, vibration, air current and optogenetic stimulation; larval video behavior and chordotonal-neuron calcium imaging",
        "задача": "Quantify stimulus-specific larval escape actions and test sensory-neuron contributions",
        "метод": "High-throughput arena and LARA video analysis; class IV and chordotonal neuron silencing or optogenetic activation; GCaMP3 imaging of chordotonal responses to vibration",
        "датасет": "Drosophila melanogaster third-instar larvae; wandering-stage animals in the nociception assay and foraging-stage animals in other assays; group-specific N in figures",
        "производительность": "Figure 5: thermal rolling in painless1 and painless3 mutants was 11.9% (N=126) and 6.1% (N=181), versus 49.1% (N=53) and 31.1% (N=45) in matched controls",
        "кросс_субъект": "not_applicable: no subject-level predictive model",
        "релевантность": 4,
        "ограничения": "Behavior and chordotonal calcium activity were measured in distinct assays; heat-evoked rolling is protective behavior rather than a subjective-pain measure. No connectome-derived dynamic model, human ECAP or SCS outcome was tested. The paper gives per-experiment counts but no single study denominator.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({"doi": "10.1371/journal.pone.0071706", "pmid": "23977118", "exact_url": URL})
    record["provenance"].update({
        "import_source": "NS-03 backward-citation primary PLOS article",
        "retrieved_at": DATE,
        "search_stream": "NS-03",
        "query_or_seed": "S212/S282 backward citations; Ohyama 2013 escape behavior",
        "iteration": 4,
    })
    record["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": "Third-instar wandering or foraging larvae, depending on assay",
        "subject_domain": "drosophila_larva",
        "modalities": ["neural_activity", "behavior", "movement_pose"],
        "sample_size": None,
        "target_construct": "nociceptive_response",
        "target_label": "Rolling and escape crawling after noxious heat; modality-specific head casting, hunching and crawling after mechanical or optogenetic stimulation",
        "access_status": "open",
        "evidence_role": "method_baseline",
    })
    record["validation"].update({
        "status": "verified_primary", "screening_status": "included_core",
        "full_text_status": "checked", "checked_at": DATE,
        "split_unit": "not_applicable", "cross_subject": "not_applicable",
        "external_validation": "not_applicable", "calibration": "not_applicable",
        "uncertainty": "not_reported", "exclusion_reason": None,
        "notes": "Primary PLOS version of record checked. Heat-linked class IV manipulation and rolling, and vibration-linked chordotonal calcium imaging, are separate results; no direct subjective-pain inference.",
    })
    record["relations"] = []
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "авторы": "Article byline",
        "год": "Article header: published 20 August 2013",
        "издание": "Citation: PLOS ONE 8(8):e71706",
        "модальность": "Abstract; Materials and Methods, Behavior Apparatus and GCaMP Imaging",
        "задача": "Abstract, stimulus-specific escape strategies",
        "метод": "Materials and Methods, Fly Stocks, Behavior Apparatus, GCaMP Imaging and Data Analysis",
        "датасет": "Materials and Methods, Fly Stocks: wandering and foraging third-instar stage by assay",
        "производительность": "Results, Figure 5 legend: painless mutant and control rolling probabilities and N",
        "кросс_субъект": "Methods: experimental larval behavior and imaging, no subject-level prediction",
        "ограничения": "Results, Figures 2, 5 and 6; Discussion",
        "evidence.species": "Abstract; Methods, Fly Stocks",
        "evidence.population": "Methods, Fly Stocks: larval stage by assay",
        "evidence.sample_size": "Results, figure legends give assay-specific N; no common total N",
        "evidence.target_construct": "Results, Thermal Noxious Stimulation Evokes a Dynamic Sequence of Escape Reactions",
        "evidence.target_label": "Results, Figures 2, 5, 6 and 9",
        "validation.split_unit": "Methods: no trained prediction model",
        "validation.cross_subject": "Methods: fly experiments only",
        "validation.external_validation": "Methods: no external prediction test",
        "validation.calibration": "Methods: no probabilistic prediction model",
        "validation.uncertainty": "Figures give group variation; model uncertainty is not reported",
        "validation.notes": "Abstract; Results, Figures 2-9; Discussion",
    }
    for path, locator in locators.items():
        field = record["field_resolution"][path]
        field["reason"] = "Checked in the primary PLOS full text; assay scope and outcome are stated separately."
        field["locators"] = [{"url": URL, "locator": locator}]
    record["field_resolution"]["evidence.sample_size"].update({
        "state": "not_reported", "value": None,
        "reason": "Per-figure animal counts are given, but no single whole-study denominator is reported.",
    })
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/23977118/", "locator": "PMID and DOI"}
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
