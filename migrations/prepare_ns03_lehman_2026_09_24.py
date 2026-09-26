"""Prepare Lehman et al. as a primary larval defensive-circuit source."""

# ruff: noqa: E501 -- precise source locators are kept in full.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns03-lehman-defensive-actions-2025.json"
URL = "https://www.nature.com/articles/s41467-025-56185-2"
DATE = "2026-09-24"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S769":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Maxime Lehman; Chloé Barré; Md Amit Hasan; Benjamin Flament; Sandra Autran; Neena Dhiman; Peter Soba; Jean-Baptiste Masson; Tihana Jovanic",
            "год": 2025,
            "издание": "Nature Communications 16:1120",
            "модальность": "Larval EM connectome, GCaMP6s calcium imaging, optogenetic and mechanical/thermal perturbations, video-scored behavior",
            "задача": "Map the interneurons mediating competition between startle and escape actions under aversive sensory context",
            "метод": "CATMAID reconstruction of A19c and descending neurons in a reference larval CNS EM volume; Kir2.1 silencing and CsChrimson activation; calcium imaging of A19c/TDN responses; blinded von Frey and hot-probe behavioral assays",
            "датасет": "Reference EM volume from a 6-hour-old larva; separate staged third-instar larvae for behavioral and calcium experiments; source data and Zenodo 10.5281/zenodo.13889569",
            "производительность": "Fig. 4: silencing R11A07 neurons reduced C-shape and rolling after 50 mN mechanical stimulation (n=63/60/60 by genotype) but did not change rolling latency under a 46 C hot probe (n=70/99/90)",
            "кросс_субъект": "not_applicable: no human-subject prediction task",
            "релевантность": 4,
            "ограничения": "The EM reference larva and third-instar behavioral animals are not the same individuals. Calcium responses test circuit interactions; rolling and C-shape are protective behaviors, not subjective pain. No connectome-constrained dynamical model, human ECAP, or SCS outcome is tested.",
            "тип_источника": "метод",
        }
    )
    record["identifiers"].update(
        {
            "doi": "10.1038/s41467-025-56185-2",
            "pmid": "39875414",
            "exact_url": URL,
        }
    )
    record["provenance"].update(
        {
            "import_source": "NS-03 primary Nature Communications article and Europe PMC JATS",
            "retrieved_at": DATE,
            "search_stream": "NS-03",
            "query_or_seed": "Drosophila larvae nociceptive defensive circuit 2025 connectome",
            "iteration": 3,
        }
    )
    record["evidence"].update(
        {
            "species": "Drosophila melanogaster",
            "population": "Larval CNS EM specimen (6 hours old) and separate third-instar larvae in physiological/behavioral experiments",
            "subject_domain": "drosophila_larva",
            "modalities": ["connectome", "neural_activity", "behavior", "movement_pose"],
            "sample_size": None,
            "target_construct": "nociceptive_response",
            "target_label": "Mechanical C-shape/rolling and thermal rolling latency; startle-versus-escape actions under contextual stimulation",
            "access_status": "open",
            "evidence_role": "simulation_foundation",
        }
    )
    record["validation"].update(
        {
            "status": "verified_primary",
            "screening_status": "included_core",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": "Primary publisher article and Europe PMC JATS checked. Circuit anatomy, neural calcium response and defensive behavior remain distinct; no subjective-pain inference.",
        }
    )
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Article byline",
        "год": "Article header: published 28 January 2025",
        "издание": "Article header: volume 16, article 1120",
        "модальность": "Abstract; Methods > Calcium imaging, EM reconstruction, nociceptive assays",
        "задача": "Abstract and Introduction final paragraph",
        "метод": "Results > R11A07 neurons are required for mechano-nociception; Methods > EM reconstruction, Calcium imaging, Mechano- and thermo-nociceptive assays",
        "датасет": "Methods > EM reconstruction: 6-hour-old larval reference; Methods > nociceptive assays: third-instar animals; Data availability",
        "производительность": "Results > R11A07 neurons are required for mechano-nociception, Figure 4a-b",
        "кросс_субъект": "Methods: larval circuit and behavioral experiments, no human task",
        "ограничения": "Methods > EM reconstruction and nociceptive assays; Discussion",
        "evidence.species": "Abstract and Methods",
        "evidence.population": "Methods > EM reconstruction and nociceptive assays",
        "evidence.sample_size": "Figure 4 reports per-genotype n; no single whole-study denominator",
        "evidence.target_construct": "Results > R11A07 neurons are required for mechano-nociception",
        "evidence.target_label": "Figure 4a-b and Methods > Mechano- and thermo-nociceptive assays",
        "validation.split_unit": "Methods: no trained subject-level prediction task",
        "validation.cross_subject": "Methods: Drosophila larvae only",
        "validation.external_validation": "Results and Methods: no independent external prediction test",
        "validation.calibration": "Results: no probabilistic predictive model requiring calibration",
        "validation.uncertainty": "Figure 4 gives group tests; no model uncertainty analysis",
        "validation.notes": "Abstract; Results Figures 4, 6 and 7; Methods",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = (
            "Checked in the primary publisher full text; anatomy, neural response and behavior are separated."
        )
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update(
        {
            "state": "not_reported",
            "value": None,
            "reason": "Per-experiment and per-genotype sample sizes are reported, but no single whole-study denominator exists.",
        }
    )
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/39875414/", "locator": "PMID and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
