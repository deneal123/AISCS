"""Publish the Sapkal et al. 2026 walking/connectome study as S763."""

# ruff: noqa: E501 -- retain exact primary section and figure locators.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from migrations.add_connectome_prior_art_2026_09_24 import _record
from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "sapkal-walking-2026-09-24.json"
DATE = "2026-09-24"
PRIMARY = "https://www.biorxiv.org/content/10.64898/2026.04.29.721658v2.full"


def candidates() -> list[dict]:
    record = _record(
        source_id="S763",
        title="Central versus peripheral neural control of a coordinated walking pattern in Drosophila",
        authors="Neha Sapkal; Divya S. Kumar; Suhas Sunke; Nino Mancini; Jason Pitchford; Kazuma Murakami; Salil S. Bidaye",
        year=2026,
        venue="bioRxiv v2",
        source_type="препринт",
        url=PRIMARY,
        doi="10.64898/2026.04.29.721658",
        species="Drosophila melanogaster",
        population="Adult flies, mainly male with a specified female FeCO-silencing experiment; MANC, MaleCNS and BANC connectome reference specimens",
        subject_domain="drosophila_adult",
        modalities=["connectome", "movement_pose", "behavior"],
        method="Optogenetic stimulation and sensory-deprivation walking assays guide a cross-connectome search for candidate CPG motifs",
        dataset="MANC v1.2.3, MaleCNS v0.9 and BANC v626; behavioral sample sizes vary by assay",
        result="Reports leg-specific rhythmic stepping under reduced sensory feedback and a recurrent CPG candidate motif; shares some candidate neurons with Pugliese et al. but is not a direct validation of its four simulation matrices.",
        limitations="bioRxiv v2; connectome-guided anatomical candidate selection plus fly behavioral experiments, without a dynamic network model in this study. The authors acknowledge seeing Pugliese modeling results before publication; candidate overlap is not independent blind validation. No nociception, pain, ECAP or SCS outcome.",
        risk_flags=["preprint", "animal_to_human_transfer_unvalidated", "future_or_recent_record_requires_recheck"],
    )
    record["задача"] = "Identify central and peripheral contributions to adult fly walking and connectome-guided candidate CPG motifs"
    record["кросс_субъект"] = "not_applicable"
    record["provenance"] = {
        "import_source": "SRC-03 connectome/VNC primary full-text search",
        "retrieved_at": DATE,
        "search_stream": "NS-01/NS-02",
        "query_or_seed": "Central versus peripheral neural control Drosophila MANC MaleCNS BANC",
        "iteration": 5,
    }
    record["evidence"].update({
        "sample_size": "Figure 1e: 60-70 trials from 6-7 flies per genotype and condition; other assays have separate denominators",
        "target_construct": "not_applicable",
        "target_label": "Walking rhythm, leg kinematics and candidate premotor CPG motif",
        "evidence_role": "method_baseline",
    })
    record["validation"].update({
        "external_validation": "not_applicable",
        "notes": "Primary bioRxiv v2 full text checked. MANC v1.2.3, MaleCNS v0.9 and BANC v626 are the versions used for this paper's motif search, not proven source releases for Pugliese S740 simulation matrices. Biological assays support walking circuitry, not a pain or human SCS endpoint.",
    })
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "evidence.population": "Methods > Fly husbandry and experimental genotypes: male flies unless indicated; FeCO-silencing experiment uses females",
        "evidence.sample_size": "Figure 1e legend: 60 to 70 trials across 6 to 7 flies per genotype and condition; Methods points to Supplementary Tables 1 and 2 for other assays",
        "датасет": "Methods > Connectome analysis > Finding putative CPG-motif: MANC v1.2.3, MaleCNS v0.9, BANC v626",
        "метод": "Results > Kinematics-guided connectome search; Methods > Connectome analysis; Methods > Behavioral recording",
        "производительность": "Results > Kinematics-guided connectome search; Discussion > Empirical evidence for walking CPG in Drosophila",
        "ограничения": "Discussion compares candidate neurons with Pugliese et al.; Acknowledgments state Pugliese modeling results were shared before publication",
        "validation.notes": "Methods > Connectome analysis; Discussion comparison with Pugliese et al.; Acknowledgments",
    }
    for path, locator in locators.items():
        record["field_resolution"][path]["locators"] = [{"url": PRIMARY, "locator": locator}]
    return [record]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    atomic_write_json(INBOX, candidates())
    result = publish_candidates(DATA, INBOX, apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != "integrity"}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
