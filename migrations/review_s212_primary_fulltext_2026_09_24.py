"""Resolve S212 larval stimulus, activity and behavior from primary JATS text."""

# ruff: noqa: E501 -- detailed measurements and primary locators are intentionally explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/PPR1092389/fullTextXML"
XML_SHA256 = "A36F35C84B282DEFEBF7CCDC48DE5E802C7DA62ED82E8308F42C2C305BC64E53"


def field(value: str, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": "reported",
        "value": value,
        "reason": (
            "Conservative inference from the measured endpoints; subjective pain and human transfer are not tested."
            if boundary else "Directly described in the primary preprint full text."
        ),
        "checked_at": DATE,
        "locators": [{"url": XML, "locator": locator}],
    }


def resolve(source: dict, path: str, value: object, locator: str) -> None:
    source["field_resolution"][path] = {
        "state": "reported",
        "value": value,
        "reason": "Primary preprint JATS full text checked through Europe PMC; separate cohorts and endpoints retained.",
        "checked_at": DATE,
        "locators": [{"url": XML, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S212")
    if any(item["source_id"] == "S212" for item in audit["entries"]):
        raise ValueError("S212 already audited")
    if "S212" not in audit["meta"]["remaining_source_ids"]:
        raise ValueError("S212 not in remaining set")

    source["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": "One first-instar CNS for matched light-sheet/EM mapping; separate third-instar preparations for neuron validation and early third-instar larvae for rolling assays",
        "subject_domain": "drosophila_larva",
        "modalities": ["neural_activity", "connectome", "behavior"],
        "sample_size": "One first-instar CNS for whole-brain/EM registration; approximately 40 early third-instar larvae per behavioral recording; validation animals counted by experiment",
        "target_label": "Basin-evoked calcium activity and separately measured rolling escape",
        "access_status": "open",
    })
    source["метод"] = "Same-specimen larval light-sheet calcium imaging and eFIB-SEM registration, followed by targeted two-photon validation and a separate rolling assay"
    source["датасет"] = "Larva1099 first-instar CNS; separate third-instar neural and behavioral preparations"
    source["производительность"] = "119 of roughly 3,000 brain neurons responded to Basin activation; 25 lineages identified; KC silencing mildly reduced rolling"
    source["ограничения"] = (
        "One first-instar CNS underlies whole-brain imaging and EM registration; validation and rolling assays use other third-instar larvae. "
        "Optogenetic Basin stimulation is an experimental proxy for nociceptive input. Calcium responses, circuit anatomy and rolling are distinct endpoints; none measures subjective pain or establishes human transfer."
    )
    source["validation"].update({
        "full_text_status": "checked",
        "checked_at": DATE,
        "external_validation": "no",
        "notes": "Europe PMC primary JATS full text checked. Same first-instar CNS for brain-wide light-sheet/EM; selected neuron responses were checked by two-photon imaging in other third-instar preparations, and rolling was tested separately in freely moving early third-instar larvae. This is within-study biological corroboration, not external validation or pain measurement.",
    })
    values = {
        "evidence.species": (source["evidence"]["species"], "JATS Results §S25 and Methods §S19, §S23"),
        "evidence.population": (source["evidence"]["population"], "JATS Results §S25, §S28-29; Methods §S19 and §S23"),
        "evidence.subject_domain": ("drosophila_larva", "JATS Results §S25 and Methods §S19, §S23"),
        "evidence.modalities": (source["evidence"]["modalities"], "JATS Results §S25-29"),
        "evidence.sample_size": (source["evidence"]["sample_size"], "JATS Results §S25 and Methods §S23; counts refer to different experiments"),
        "evidence.target_label": (source["evidence"]["target_label"], "JATS Results §S25-29"),
        "evidence.access_status": ("open", "Europe PMC PPR1092389 primary fullTextXML retrieved on 2026-09-24"),
        "метод": (source["метод"], "JATS Methods §S4, §S20, §S23 and Results §S25"),
        "датасет": (source["датасет"], "JATS Results §S25 and Methods §S19, §S23"),
        "производительность": (source["производительность"], "JATS Results §S25-26 and §S29"),
        "ограничения": (source["ограничения"], "JATS Results §S25-29 and Discussion §S30"),
        "validation.checked_at": (DATE, "Europe PMC PPR1092389 fullTextXML retrieved on 2026-09-24"),
        "validation.external_validation": ("no", "JATS Results §S28-29: within-study neural and behavioral tests"),
        "validation.notes": (source["validation"]["notes"], "JATS Results §S25, §S28-29; Methods §S19 and §S23"),
    }
    for path, (value, locator) in values.items():
        resolve(source, path, value, locator)

    audit["entries"].append({
        "source_id": "S212",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field("First-instar isolated CNS: 18 optogenetic Basin-Chronos presentations, 200 s apart, during whole-brain imaging. Separate early third-instar rolling assay: Basin-Chrimson activation with or without KC inhibition.", "JATS Results §S25, Methodology for overlaying brainwide activity and connectivity maps; Methods §S23, Behavioural experiments"),
            "neural_response": field("Pan-neuronal RGECO1a light-sheet signals in one first-instar CNS identified 119 of about 3,000 brain neurons responding to Basin activation across 25 lineages; responses of KC, DNsez-1 and CSD were checked by targeted GCaMP8s imaging in additional larvae.", "JATS Results §S25-28; Figures 2, 3 and 5"),
            "behavior": field("Freely moving early third-instar larvae: rolling percentage within five seconds after Basin activation; KC silencing caused a mild significant reduction. Approximately 40 larvae were placed per recording, and only first light-on responses were analyzed.", "JATS Methods §S23, Behavioural experiments; Results §S29 and Figure 5C"),
            "pain_boundary": field("Basin-evoked neural activity, mapped anatomy and larval rolling are separate observations; the paper does not directly measure subjective pain or human clinical transfer.", "JATS Abstract, Results §S25-29 and Discussion §S30", boundary=True),
        },
        "primary_fulltext_sha256": XML_SHA256,
        "cohort_boundary": "The first-instar same-specimen imaging/EM dataset and the third-instar validation and behavioral assays must not be counted as one cohort.",
    })
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["remaining_source_ids"].remove("S212")
    audit["meta"]["remaining_primary_access"] = [
        item for item in audit["meta"]["remaining_primary_access"] if item["source_id"] != "S212"
    ]
    report = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    report.update(completeness_summary(records["sources"]))
    return records, audit, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit, report = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s212-primary-fulltext-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-nociception-audit.json", audit)
        atomic_write_json(DATA / "completeness-report.json", report)
        print(f"Applied S212 full-text review; snapshot: {snapshot}")
    else:
        print("Dry run: 16 of 17 NS-03 candidates audited; S282 remains")


if __name__ == "__main__":
    main()
