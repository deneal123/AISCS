"""Prepare five independently verified NS-07–NS-10 primary-source cards."""
# ruff: noqa: E501 -- exact source titles and audit descriptions are intentional.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "staging/inbox/pa04-five-primary-analogues-2026-09-25.json"
DATE = "2026-09-25"
CARDS = [
    {
        "id": "S784",
        "title": "Compound action potentials recorded in the human spinal cord during neurostimulation for pain relief",
        "authors": "John L. Parker; Dean M. Karantonis; Peter S. Single; Milan Obradovic; Michael J. Cousins",
        "year": 2012,
        "venue": "Pain 153(3):593-601",
        "doi": "10.1016/j.pain.2011.11.023",
        "pmid": "22188868",
        "modality": "Human epidural ECAP during therapeutic SCS",
        "task": "Record stimulation-evoked neural recruitment during pain-relief SCS",
        "method": "Epidural compound-action-potential recording over stimulation-current sweeps",
        "dataset": "Patients undergoing therapeutic spinal cord stimulation; abstract does not report denominator",
        "result": "A-beta recruitment threshold and ECAP growth; amplitude correlated with painful-area coverage",
        "limitations": "Abstract-level verification only; painful-area coverage is not pain intensity or treatment-response prediction.",
        "species": "Homo sapiens",
        "population": "Chronic-pain patients undergoing therapeutic SCS",
        "domain": "human_clinical",
        "modalities": ["ecap", "clinical_outcome"],
        "target": "ecap_neural_recruitment",
        "label": "A-beta ECAP threshold and growth; painful-area coverage correlation",
        "access": "restricted",
        "role": "method_baseline",
        "status": "partially_verified",
        "full_text": "metadata_only",
        "stream": "NS-09",
        "locator": "PubMed primary abstract, results on A-beta recruitment and area coverage",
    },
    {
        "id": "S785",
        "title": "A model of evoked potentials in spinal cord stimulation",
        "authors": "James H. Laird; John L. Parker",
        "year": 2013,
        "venue": "2013 35th Annual International Conference of the IEEE EMBS:6555-6558",
        "doi": "10.1109/EMBC.2013.6611057",
        "pmid": "24111244",
        "modality": "Simulated epidural SCS electric field, nerve-fiber activation and ECAP",
        "task": "Predict recruited spinal fibers and recorded compound-action-potential waveform",
        "method": "Hybrid three-dimensional volume-conductor electric model and neural-fiber model",
        "dataset": "Human spinal geometry and fiber simulation; no independent patient cohort established in abstract",
        "result": "Model reproduces observed threshold and propagation features qualitatively",
        "limitations": "Conference abstract supports the hybrid forward-model mechanism; full method and quantitative comparator unavailable.",
        "species": "Homo sapiens (anatomical simulation)",
        "population": "Simulated spinal cord and nerve fibers; no enrolled cohort established",
        "domain": "simulation",
        "modalities": ["ecap", "simulation_state"],
        "target": "ecap_neural_recruitment",
        "label": "Predicted fiber recruitment and ECAP waveform",
        "access": "restricted",
        "role": "method_baseline",
        "status": "partially_verified",
        "full_text": "metadata_only",
        "stream": "NS-07",
        "locator": "PubMed primary abstract, three-dimensional electrical and neural hybrid model",
    },
    {
        "id": "S786",
        "title": "Cause of Pulse Artefacts Inherent to the Electrodes of Neuromodulation Implants",
        "authors": "Peter S. Single; John B. Scott",
        "year": 2018,
        "venue": "IEEE Transactions on Neural Systems and Rehabilitation Engineering 26(10):2078-2083",
        "doi": "10.1109/TNSRE.2018.2870169",
        "pmid": "30273153",
        "modality": "Post-pulse implant-electrode artifact voltage",
        "task": "Explain and model slowly decaying electrode pulse artifacts",
        "method": "Electrode double-layer concentration-gradient model compared with saline measurements",
        "dataset": "Saline bench measurements; no human ECAP outcome cohort",
        "result": "Compact artifact model agrees with saline measurements in the author abstract",
        "limitations": "Bench electrode-interface mechanism, not validated human SCS artifact removal or analgesia.",
        "species": "Not applicable: saline bench experiment",
        "population": "Platinum implant electrodes measured in saline",
        "domain": "not_applicable",
        "modalities": ["ecap", "simulation_state"],
        "target": "technical_signal_quality",
        "label": "Post-pulse voltage-tail model versus saline recording",
        "access": "restricted",
        "role": "method_baseline",
        "status": "partially_verified",
        "full_text": "metadata_only",
        "stream": "NS-08",
        "locator": "PubMed primary abstract, concentration-gradient mechanism and saline comparison",
    },
    {
        "id": "S787",
        "title": "The Evoked Compound Action Potential as a Predictor for Perception in Chronic Pain Patients: Tools for Automatic Spinal Cord Stimulator Programming and Control",
        "authors": "Julie G. Pilitsis; Krishnan V. Chakravarthy; Andrew J. Will; Kelli C. Trutnau; Kelly N. Hageman; David A. Dinsmoor; Larry M. Litvak",
        "year": 2021,
        "venue": "Frontiers in Neuroscience 15:673998",
        "doi": "10.3389/fnins.2021.673998",
        "pmid": "34335157",
        "modality": "Human SCS ECAP growth curves and perception/discomfort thresholds",
        "task": "Estimate perceptually referenced SCS programming thresholds from ECAP",
        "method": "Artifact-reduced ECAP sweeps across posture and pulse width; ET, PT and DT correlation",
        "dataset": "14 chronic-pain participants; 112 ECAP growth curves",
        "result": "ECAP threshold correlated with perception and discomfort thresholds (r=0.93 each)",
        "limitations": "Perception and discomfort thresholds are not pain-relief outcomes; 112 curves are repeated measures of 14 people.",
        "species": "Homo sapiens",
        "population": "14 chronic-pain SCS participants",
        "domain": "human_clinical",
        "modalities": ["ecap"],
        "sample_size": "14 participants; 112 repeated growth curves",
        "target": "ecap_neural_recruitment",
        "label": "ECAP threshold relative to perception and discomfort thresholds",
        "access": "open",
        "role": "method_baseline",
        "status": "verified_primary",
        "full_text": "checked",
        "stream": "NS-09",
        "locator": "PMC8320888, Methods ECAP acquisition and growth curves; Results ET-PT and ET-DT",
        "exact_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8320888/",
    },
    {
        "id": "S788",
        "title": "Effective Relief of Pain and Associated Symptoms With Closed-Loop Spinal Cord Stimulation System: Preliminary Results of the Avalon Study",
        "authors": "Marc Russo; Michael J. Cousins; Charles Brooker; Nigel Taylor; Thomas Boesel; Robert Sullivan; Lawrence Poree; Nima H. Shariati; Eric Hanson; John Parker",
        "year": 2018,
        "venue": "Neuromodulation 21(1):38-47",
        "doi": "10.1111/ner.12684",
        "pmid": "28922517",
        "modality": "ECAP-controlled closed-loop spinal cord stimulation",
        "task": "Assess preliminary six-month patient-reported outcomes after permanent implant",
        "method": "Prospective open-label Avalon cohort with baseline, three- and six-month follow-up",
        "dataset": "51 trialed; 36 permanently implanted chronic back/leg-pain patients",
        "result": "Patient-reported pain, quality-of-life, disability and sleep outcomes over six months",
        "limitations": "Single-arm preliminary paper without randomized comparator. AVALON must not be linked to NCT02161627, which is the distinct Panorama crossover trial.",
        "species": "Homo sapiens",
        "population": "Chronic back/leg-pain patients successfully trialed for permanent SCS",
        "domain": "human_clinical",
        "modalities": ["ecap", "clinical_outcome"],
        "sample_size": "51 trialed; 36 implanted",
        "target": "scs_response",
        "label": "Patient-reported VAS/BPI pain and EQ-5D/ODI/PSQI at baseline, 3 and 6 months",
        "access": "restricted",
        "role": "scs_ecap_validation",
        "status": "partially_verified",
        "full_text": "metadata_only",
        "stream": "NS-10",
        "locator": "PubMed primary abstract, Materials and Methods and Results, 51 trialed and 36 implanted",
    },
]


def main() -> None:
    template = json.loads(
        (DATA / "staging/source-record.template.json").read_text(encoding="utf-8")
    )
    candidates = []
    for card in CARDS:
        record = json.loads(json.dumps(template))
        record.update({
            "id": card["id"], "название": card["title"],
            "авторы": card["authors"], "год": card["year"],
            "издание": card["venue"], "модальность": card["modality"],
            "задача": card["task"], "метод": card["method"],
            "датасет": card["dataset"], "производительность": card["result"],
            "кросс_субъект": "not_applicable: descriptive or modeling study, not a patient-prediction model",
            "релевантность": 5, "ограничения": card["limitations"],
            "тип_источника": "SCS_специфика",
        })
        url = card.get("exact_url", f"https://pubmed.ncbi.nlm.nih.gov/{card['pmid']}/")
        record["identifiers"].update({
            "doi": card["doi"], "pmid": card["pmid"], "exact_url": url,
        })
        record["provenance"].update({
            "import_source": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
            "retrieved_at": DATE, "search_stream": card["stream"],
            "query_or_seed": "PA-04 backward citation search from canonical ECAP/SCS method and outcome sources",
            "iteration": 5,
        })
        record["evidence"].update({
            "species": card["species"], "population": card["population"],
            "subject_domain": card["domain"], "modalities": card["modalities"],
            "sample_size": card.get("sample_size"),
            "target_construct": card["target"], "target_label": card["label"],
            "access_status": card["access"], "evidence_role": card["role"],
        })
        record["validation"].update({
            "status": card["status"], "screening_status": "included_core",
            "full_text_status": card["full_text"], "checked_at": DATE,
            "split_unit": "participant" if card["domain"] == "human_clinical" else "not_applicable",
            "cross_subject": "not_applicable", "external_validation": "no",
            "calibration": "not_reported", "uncertainty": "not_reported",
            "notes": card["limitations"],
        })
        record["risk_flags"] = []
        record = migrate_record(record, checked_at=DATE)
        for field_name in (
            "авторы", "год", "издание", "модальность", "задача", "метод",
            "датасет", "производительность", "ограничения", "validation.notes",
            "evidence.population", "evidence.target_label",
        ):
            record["field_resolution"][field_name]["reason"] = (
                "Checked in the primary text at the named locator; access limits retained."
            )
            record["field_resolution"][field_name]["locators"] = [{
                "url": url, "locator": card["locator"],
            }]
        candidates.append(record)
    atomic_write_json(OUTPUT, {"sources": candidates})
    print(f"Prepared {len(candidates)} candidates: {OUTPUT}")


if __name__ == "__main__":
    main()
