"""Record what the official 3DPain implementation proves about UNBC labels."""

# ruff: noqa: E501 -- primary-source findings and URLs are deliberately explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
SHA = "b580e7c7d9af16d8df862bb4697ce2133ced9d37"
CODE = f"https://github.com/TaatiTeam/Pain-in-3D/blob/{SHA}"
PAPER = "https://arxiv.org/html/2509.16727"


def locator(path: str, lines: str) -> dict:
    return {"url": f"{CODE}/{path}", "locator": lines}


CODE_LOCATORS = [
    locator("README.md", "Training, Stage 2: synthetic checkpoint followed by UNBC fivefold fine-tuning"),
    locator("data/unbc_loader.py", "Lines 87-114: label_AU_* and label_pspi loaded from UNBC annotations"),
    locator("data/unbc_loader.py", "Lines 149-184: subject-disjoint train and validation groups for each fold"),
    locator("train_unbc.py", "Lines 28-40, 60-64 and 114-121: UNBC datamodule, synthetic checkpoint, trainer.fit and test"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records_path = DATA / "records.json"
    synthetic_path = DATA / "synthetic-domain-audit.json"
    ns06_path = DATA / "ns06-prior-art-audit.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8"))
    ns06 = json.loads(ns06_path.read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S759")
    entry = next(item for item in synthetic["entries"] if item["source_id"] == "S759")
    decision = next(item for item in ns06["analogue_decisions"] if item["source_id"] == "S759")
    if ns06.get("s759_author_code_check"):
        raise ValueError("Author code has already been reviewed")

    source["ограничения"] = (
        "Visual PSPI task with subject-disjoint UNBC fivefold evaluation and no independent second real dataset. "
        "The v5 manuscript calls UNBC reserved for evaluation, but the official implementation at the reviewed commit "
        "fine-tunes on labeled UNBC training folds after synthetic pretraining. The code resolves the executable protocol, "
        "while provenance of every reported paper result to this commit remains unverified. No physiological synthetic "
        "modality or unlabeled-target alignment as in S149."
    )
    source["validation"]["notes"] = (
        "Synthetic identity-disjoint 70/20/10 and UNBC subject-disjoint fivefold splits are reported. Official author code "
        "loads real UNBC PSPI/AU labels, trains on each fold's training subjects, and evaluates held-out subjects. "
        "This resolves the available implementation's real-label role, although the v5 manuscript remains internally "
        "inconsistent and exact paper-result provenance to the reviewed commit is unverified."
    )
    for key, value in (("ограничения", source["ограничения"]), ("validation.notes", source["validation"]["notes"])):
        resolution = source["field_resolution"][key]
        resolution["value"] = value
        resolution["reason"] = "Preprint version 5 is compared with the official pinned implementation; result provenance is not asserted."
        resolution["checked_at"] = DATE
        resolution["locators"] = [
            {"url": PAPER, "locator": "v5, Section 5 Implementation Details and Ablation Studies"},
            *CODE_LOCATORS,
        ]

    real = entry["extraction"]["real_data_provenance"]
    real["value"] = (
        "82,500 synthetic frames from 2,500 identities and UNBC real frames from 25 participants. "
        "Official code loads real UNBC PSPI/AU labels and fine-tunes on each fold's training subjects after synthetic pretraining; "
        "the paper's exact reported-run provenance to this commit is not verified."
    )
    real["reason"] = "Preprint v5 and pinned official author code; paper/code discrepancy retained."
    real["locators"].extend(CODE_LOCATORS)
    leakage = entry["extraction"]["leakage_control"]
    leakage["value"] = (
        "Synthetic identity-disjoint 70/20/10 and UNBC subject-disjoint fivefold splits are reported; official code uses "
        "labeled real training subjects inside each fold. Exact reported-run configuration and neutral-reference selection "
        "across folds have not been independently reproduced."
    )
    leakage["reason"] = "Preprint v5 and pinned official author code; no runtime reproduction."
    leakage["locators"].extend(CODE_LOCATORS)
    decision["relation_to_s149"] = (
        "Visual PSPI synthetic pretraining followed by supervised real UNBC fivefold fine-tuning in official code, "
        "rather than S149's multimodal synthetic-source unlabeled-target alignment; paper v5 wording conflicts with code."
    )
    decision["certainty"] = "primary_full_text_and_author_code_with_result_provenance_limit"
    ns06["s759_author_code_check"] = {
        "state": "executable_protocol_resolved_reported_runs_unverified",
        "checked_at": DATE,
        "commit": SHA,
        "finding": "Official code loads labeled UNBC PSPI/AU data and trains on real training subjects in every fivefold split after synthetic pretraining; the v5 manuscript's evaluation-only wording conflicts with this. No run manifest links its reported metrics to the pinned code commit.",
        "locators": [
            {"url": PAPER, "section": "v5, Section 5 Implementation Details and Ablation Studies"},
            *({"url": item["url"], "section": item["locator"]} for item in CODE_LOCATORS),
        ],
    }
    ns06["remaining"] = [
        item for item in ns06["remaining"]
        if not item.startswith("Resolve S759 version-5 wording")
    ]
    ns06["remaining"].insert(
        1,
        "Link S759 reported-result runs to a code commit or manifest if exact provenance is required; the executable protocol is resolved but the manuscript conflict remains documented.",
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s759-author-code-review")
        atomic_write_json(records_path, records)
        atomic_write_json(synthetic_path, synthetic)
        atomic_write_json(ns06_path, ns06)
        print(f"Applied S759 author-code review; snapshot: {snapshot}")
    else:
        print("Dry run: S759 real-label implementation resolved, paper-result provenance limited")


if __name__ == "__main__":
    main()
