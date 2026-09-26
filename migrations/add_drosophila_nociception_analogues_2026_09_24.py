"""Publish two primary larval nociception circuit experiments."""

# ruff: noqa: E501 -- exact titles and primary-method locators are retained.

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "drosophila-nociception-analogues-2026-09-24.json"
DATE = "2026-09-24"
SPECS = (
    {
        "id": "S760",
        "title": "Descending GABAergic pathway links brain sugar-sensing to peripheral nociceptive gating in Drosophila",
        "authors": "Mami Nakamizo-Dojo; Kenichi Ishii; Jiro Yoshino; Masato Tsuji; Kazuo Emoto",
        "year": 2023,
        "journal": "Nature Communications 14:6515",
        "doi": "10.1038/s41467-023-42202-9",
        "pmid": "37845214",
        "url": "https://www.nature.com/articles/s41467-023-42202-9",
        "modality": "Larval C4da calcium imaging, optogenetic GABAergic perturbation, and rolling behavior",
        "task": "Identify descending neural gating of larval nociceptive escape during glucose feeding",
        "method": "Genetic SDG isolation; calcium imaging and optogenetic silencing/activation; mechanical, heat and AITC escape assays",
        "dataset": "Drosophila melanogaster third-instar larvae; group-specific animal counts in Figures 1-3",
        "target_label": "C4da presynaptic activity and rolling probability, duration or latency after noxious stimulation",
        "limitations": "Stimulus-evoked neural activity and rolling are distinct observables. No subjective-pain measure, human ECAP, SCS outcome, or cross-species validation.",
        "modalities": ["neural_activity", "behavior"],
        "locators": {
            "метод": "Results, SDGs are necessary and sufficient to suppress escape behavior; Figures 2-3",
            "датасет": "Figure 1a, third-instar larvae; Figure 2 legend, group-specific independent animals",
            "evidence.target_label": "Figures 2-3, C4da synaptic activity and rolling probability/duration/latency",
            "validation.notes": "Abstract and Discussion, larval circuit and behavioral scope",
        },
    },
    {
        "id": "S761",
        "title": "Nociceptive interneurons control modular motor pathways to promote escape behavior in Drosophila",
        "authors": "Anita Burgos; Ken Honjo; Tomoko Ohyama; Cheng Sam Qian; Grace Ji-Eun Shin; Daryl M Gohl; Marion Silies; W Daniel Tracey; Marta Zlatic; Albert Cardona; Wesley B Grueber",
        "year": 2018,
        "journal": "eLife 7:e26016",
        "doi": "10.7554/eLife.26016",
        "pmid": "29528286",
        "url": "https://elifesciences.org/articles/26016",
        "modality": "Larval noxious-heat calcium imaging, EM circuit reconstruction, optogenetic perturbation, and escape behavior",
        "task": "Identify interneuron routes controlling sequential bending and rolling escape modules",
        "method": "GCaMP6m imaging of DnB heat responses; EM reconstruction; DnB/Goro activation and inactivation with larval behavior scoring",
        "dataset": "Drosophila melanogaster larvae; group-specific animal counts in figures",
        "target_label": "DnB calcium response to noxious heat and sequential body bending/rolling escape",
        "limitations": "DnB circuit activity and bend/roll behavior are objective larval measurements, not subjective pain, human spinal activity, or SCS response.",
        "modalities": ["connectome", "neural_activity", "behavior"],
        "locators": {
            "метод": "Abstract; Results, DnB calcium response and Goro perturbation",
            "датасет": "Abstract and Methods, Drosophila larvae; figures report group-specific samples",
            "evidence.target_label": "Abstract; Figure 3, DnB GCaMP6m response above 39 °C; Goro perturbation and bend/roll sequence",
            "validation.notes": "Abstract and Discussion, modular larval escape circuit scope",
        },
    },
)


def candidates() -> list[dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]
    base = next(record for record in records if record["id"] == "S066")
    result = []
    for spec in SPECS:
        record = deepcopy(base)
        record.update(
            {
                "id": spec["id"],
                "название": spec["title"],
                "авторы": spec["authors"],
                "год": spec["year"],
                "издание": spec["journal"],
                "модальность": spec["modality"],
                "задача": spec["task"],
                "метод": spec["method"],
                "датасет": spec["dataset"],
                "производительность": None,
                "кросс_субъект": None,
                "релевантность": 4,
                "ограничения": spec["limitations"],
            }
        )
        record["identifiers"] = {
            "doi": spec["doi"], "pmid": spec["pmid"], "arxiv_id": None,
            "patent_id": None, "dataset_id": None, "exact_url": spec["url"],
        }
        record["provenance"] = {
            "import_source": "SRC-04 NS-03 primary full-text review",
            "retrieved_at": DATE,
            "search_stream": "NS-03",
            "query_or_seed": spec["title"],
            "iteration": 2,
        }
        record["evidence"] = {
            "species": "Drosophila melanogaster",
            "population": "third-instar larvae" if spec["id"] == "S760" else "larvae",
            "sample_size": None,
            "target_construct": "nociceptive_response",
            "target_label": spec["target_label"],
            "access_status": "open",
            "evidence_role": "simulation_foundation",
            "subject_domain": "drosophila_larva",
            "modalities": spec["modalities"],
        }
        record["validation"] = {
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
            "notes": spec["limitations"],
        }
        record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
        record["relations"] = []
        record = migrate_record(record, checked_at=DATE)
        for path, locator in spec["locators"].items():
            record["field_resolution"][path]["locators"] = [
                {"url": spec["url"], "locator": locator}
            ]
        result.append(record)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    atomic_write_json(INBOX, candidates())
    result = publish_candidates(DATA, INBOX, apply=args.apply)
    print(json.dumps({key: value for key, value in result.items() if key != "integrity"}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
