"""Resolve S282 larval stimulus, neural response and behavior from bioRxiv PDF."""

# ruff: noqa: E501 -- preserve precise primary methods and figure locators.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
PDF = "https://www.biorxiv.org/content/10.1101/2025.09.30.679458v1.full.pdf"
PDF_SHA256 = "9F8BAAE231C20F5BF3F9AABAB8849B9D9689CBB0D1FAD7D4CFDF64225E8E98C7"


def field(value: str, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": "reported",
        "value": value,
        "reason": (
            "Conservative inference from measured larval endpoints; subjective pain and human transfer are not tested."
            if boundary else "Directly described in the primary bioRxiv v1 full text."
        ),
        "checked_at": DATE,
        "locators": [{"url": PDF, "locator": locator}],
    }


def resolve(source: dict, path: str, value: object, locator: str) -> None:
    source["field_resolution"][path] = {
        "state": "reported",
        "value": value,
        "reason": "Primary author PDF checked; experimental cohorts and proxy stimuli distinguished.",
        "checked_at": DATE,
        "locators": [{"url": PDF, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S282")
    if source["validation"]["full_text_status"] != "metadata_only":
        raise ValueError("S282 is no longer metadata-only")
    if any(item["source_id"] == "S282" for item in audit["entries"]):
        raise ValueError("S282 already audited")
    if audit["meta"]["remaining_source_ids"] != ["S282"]:
        raise ValueError("NS-03 remaining set changed")

    source["identifiers"]["exact_url"] = PDF
    source["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": "Third-instar wandering larvae in neural and behavioral assays; a separately published first-instar L1 CNS EM volume supplies the structural reference",
        "sample_size": "N=8 for each of the Goro and Ipsigoro calcium-imaging comparisons; behavioral group totals are not stated in the main PDF; eight larvae were placed per recording run",
        "target_label": "Goro and Ipsigoro calcium responses, separately from third-instar rolling escape after neural activation or inhibition",
        "access_status": "open",
    })
    source["метод"] = "Larval connectome path analysis; ex-vivo two-photon calcium imaging after optogenetic neuronal activation; separate conditioned-odor and nociceptive-proxy rolling assays"
    source["датасет"] = "Published L1 larval CNS EM connectome; separate third-instar ex-vivo imaging and behavioral preparations"
    source["производительность"] = "Ipsigoro activation increased Goro ΔF/F (Fig. 2f, N=8); MD-IV activation increased Ipsigoro ΔF/F (Fig. 3c, N=8); Ipsigoro manipulation changed rolling under thermal or MD-IV activation"
    source["ограничения"] = (
        "bioRxiv v1, without peer review. Heating activates genetically targeted Basin or MD-IV pathways and also supplies thermal context; these manipulations are nociceptive proxies, not a direct measure of subjective pain. "
        "Imaging, EM anatomy and rolling use distinct preparations; behavioral group totals are not stated in the main PDF. No human ECAP or SCS outcome."
    )
    source["validation"].update({
        "status": "verified_primary",
        "full_text_status": "checked",
        "checked_at": DATE,
        "notes": "Author bioRxiv v1 41-page PDF retrieved and checked (SHA-256 recorded in NS-03 audit). Third-instar experimental larvae are distinct from the published L1 EM reference. Goro and Ipsigoro ΔF/F, connectome paths and rolling are separate observations; no subjective pain endpoint. Behavioral total N is unavailable in the main PDF.",
    })
    values = {
        "identifiers.exact_url": (PDF, "bioRxiv v1 full PDF, posted 2025-09-30"),
        "evidence.species": (source["evidence"]["species"], "PDF p. 24, Methods, Experimental animals"),
        "evidence.population": (source["evidence"]["population"], "PDF p. 24, Methods, Experimental animals; p. 14 Fig. 3a and Methods, Connectomic analysis, L1 CNS EM"),
        "evidence.sample_size": (source["evidence"]["sample_size"], "PDF p. 9 Fig. 2f; p. 14 Fig. 3c; p. 28 Methods, Behavioural experiments"),
        "evidence.target_label": (source["evidence"]["target_label"], "PDF pp. 9-14, Figures 2-3 and Results"),
        "evidence.access_status": ("open", "bioRxiv v1 full PDF retrieved on 2026-09-24; SHA-256 9F8BAAE...E98C7"),
        "метод": (source["метод"], "PDF pp. 25-30, Methods, Functional connectivity and Behavioural experiments"),
        "датасет": (source["датасет"], "PDF p. 14 Fig. 3a; pp. 24-28 Methods"),
        "производительность": (source["производительность"], "PDF p. 9 Fig. 2e-h; p. 14 Fig. 3b-e"),
        "ограничения": (source["ограничения"], "PDF pp. 7-14 Figures 1-3; pp. 24-30 Methods"),
        "validation.checked_at": (DATE, "bioRxiv v1 full PDF retrieved on 2026-09-24"),
        "validation.notes": (source["validation"]["notes"], "PDF pp. 9, 14 Figures 2-3; pp. 24-30 Methods"),
    }
    for path, (value, locator) in values.items():
        resolve(source, path, value, locator)

    audit["entries"].append({
        "source_id": "S282",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field(
                "Third-instar assays: red-light optogenetic activation of Or42b odor neurons as conditioned cue; IR heating thermogenetically activates Basin interneurons as aversive proxy (27.5°C training, 25.1°C test). Separate Ipsigoro and MD-IV activation/inhibition assays use optogenetics or thermal dTrpA1/Shibirets1.",
                "PDF p. 7 Fig. 1a and legend; pp. 27-28 Methods, Behavioural experiments; pp. 9, 14 Figs. 2-3",
            ),
            "neural_response": field(
                "Published L1 EM paths connect MBON/ascending MD-IV pathways through Ipsigoro toward Goro. In separate third-instar ex-vivo CNS preparations, optical Ipsigoro activation increased Goro GCaMP6s ΔF/F (Fig. 2f, N=8), and MD-IV activation increased Ipsigoro GCaMP8s ΔF/F (Fig. 3c, N=8).",
                "PDF p. 9 Fig. 2a-f; p. 14 Fig. 3a-c; pp. 25-26 Methods, Functional connectivity experiments",
            ),
            "behavior": field(
                "Freely moving third-instar larvae: rolling time or probability after conditioned cue plus Basin activation, Ipsigoro thermal activation, and MD-IV thermal activation with Ipsigoro inhibition. Learning analysis uses the first test stimulation and a five-second window; behavioral group totals are not stated in the main PDF.",
                "PDF p. 7 Fig. 1b-c; p. 9 Fig. 2g-h; p. 14 Fig. 3d-e; pp. 28-30 Methods, Behavioural experiments and Statistical analysis",
            ),
            "pain_boundary": field(
                "Circuit connectivity, evoked calcium activity and larval rolling are distinct endpoints. Genetic activation and heat provide experimental nociceptive context, but no subjective pain or human clinical response is measured.",
                "PDF pp. 2, 7-14, Abstract and Figures 1-3; pp. 24-30 Methods",
                boundary=True,
            ),
        },
        "primary_fulltext_sha256": PDF_SHA256,
        "cohort_boundary": "Published first-instar L1 EM connectome, third-instar isolated CNS imaging and third-instar free-moving behavioral assays are not one cohort; N=8 imaging counts do not imply behavioral group sizes.",
    })
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["remaining_source_ids"] = []
    audit["meta"]["remaining_primary_access"] = []
    audit["meta"]["status"] = "complete"

    report = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    report.update(completeness_summary(records["sources"]))
    return records, audit, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit, report = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s282-primary-pdf-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-nociception-audit.json", audit)
        atomic_write_json(DATA / "completeness-report.json", report)
        print(f"Applied S282 full-text review; snapshot: {snapshot}")
    else:
        print("Dry run: 17 of 17 NS-03 candidates audited from primary text")


if __name__ == "__main__":
    main()
