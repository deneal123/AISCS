"""Resolve six further NS-03 records and refresh accessible source URLs."""

# ruff: noqa: E501 -- exact primary-source locators and extraction statements are retained.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = {
    "S012": "https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2022.854124/full",
    "S013": "https://digital.lib.washington.edu/researchworks/items/622bc2dc-af95-4861-bc13-a91cab65eac8/full",
    "S031": "https://elifesciences.org/articles/91582",
    "S066": "https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1012122",
    "S090": "https://cshprotocols.cshlp.org/content/2025/4/pdb.prot108128.abstract",
    "S152": "https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1076017/full",
}


def field(state: str, value: str | None, url: str, locator: str, reason: str) -> dict:
    return {
        "state": state, "value": value, "reason": reason,
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


def measured(value: str, url: str, locator: str) -> dict:
    return field("reported", value, url, locator, "Directly described by the primary source.")


def boundary(value: str, url: str, locator: str) -> dict:
    return field(
        "reported", value, url, locator,
        "Conservative inference from source scope; subjective experience is not directly measured.",
    )


def review_entry(source_id: str, description: str) -> dict:
    url = URL[source_id]
    return {
        "source_id": source_id,
        "source_role": "narrative_review",
        "extraction": {
            "stimulus": field("not_applicable", None, url, "Article type and Abstract", f"{description}; this review performs no original stimulus intervention."),
            "neural_response": field("not_applicable", None, url, "Article type and Abstract", "The review summarizes prior circuit measurements, but reports no new neural recording."),
            "behavior": field("not_applicable", None, url, "Article type and Abstract", "The review summarizes prior behaviors, but reports no new behavioral cohort."),
            "pain_boundary": boundary("Review of nociceptive assays and mechanisms; cited fly responses do not establish subjective pain or human clinical transfer.", url, "Abstract and Introduction"),
        },
    }


EXTRA = [
    review_entry("S012", "Both larval and adult Drosophila assays are discussed"),
    {
        "source_id": "S013",
        "source_role": "doctoral_thesis",
        "extraction": {
            "stimulus": measured("Adult abdominal multidendritic nociceptor optogenetic screen and heat stimulation in functional imaging", URL["S013"], "Institutional thesis record, dc.description.abstract, behavioral screen and functional imaging"),
            "neural_response": measured("Adult nociceptor functional imaging reports robust heat responses but no detectable mechanosensory activity; connectomic and single-cell RNA-seq analyses are separate layers", URL["S013"], "Institutional thesis record, dc.description.abstract, functional imaging and molecular identity"),
            "behavior": measured("Aversion screen and rapid running/jumping versus longer-term behavioral modulation attributed to distinct adult pathways", URL["S013"], "Institutional thesis record, dc.description.abstract, escape and aversion sections"),
            "pain_boundary": boundary("Adult nociceptor activity and escape/avoidance characterize threat processing; the thesis does not directly measure subjective pain.", URL["S013"], "Institutional thesis record, dc.description.abstract"),
        },
        "overlap_note": "Thesis synthesis overlaps Jones et al. preprint S029; not an independent replication cohort.",
    },
    {
        "source_id": "S031",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": measured("Larval noxious cold at or below 10 °C and targeted optogenetic activation/co-activation of CIII multidendritic neurons and downstream types", URL["S031"], "Results, Functional analysis of somatosensory neurons in cold nociception"),
            "neural_response": measured("Cold- and CIII-evoked calcium responses in sensory, Basin, premotor and projection neurons; EM connectivity provides anatomy, not activity", URL["S031"], "Abstract; Results, CaMPARI and GCaMP response sections"),
            "behavior": measured("Larval contraction: head and tail withdrawal, quantified by contraction proportion, duration and magnitude", URL["S031"], "Results, Functional analysis; Figures 1-2"),
            "pain_boundary": boundary("Cold-evoked calcium activity and contraction are distinct neural and protective behavioral observables, not subjective pain.", URL["S031"], "Abstract and Results"),
        },
    },
    {
        "source_id": "S066",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": measured("Repeated optogenetic activation of larval C4da nociceptors; stimulation frequency, intensity and developmental timing varied", URL["S066"], "Results, stimulation pattern and developmental timing; Figure 1"),
            "neural_response": measured("Sustained increased C4da sensory-neuron calcium activity after repeated activation; octopamine OAMB and VUM feedback amplify sensory output", URL["S066"], "Abstract; Results, calcium imaging and feedback; Figure 3"),
            "behavior": measured("Increased probability/intensity of nocifensive rolling and shorter rolling latency after repeated activation", URL["S066"], "Abstract; Results, rolling assays"),
            "pain_boundary": boundary("Sensory gain and rolling sensitization are measured, but neither directly establishes a subjective pain state.", URL["S066"], "Abstract and Author summary"),
        },
    },
    {
        "source_id": "S090",
        "source_role": "experimental_protocol",
        "extraction": {
            "stimulus": measured("Blue-light ChR2 activation of class-IV multidendritic nociceptors in third-instar larvae", URL["S090"], "Abstract, optogenetic technique and larval preparation"),
            "neural_response": field("not_reported", None, URL["S090"], "Abstract", "The protocol describes targeted activation but no paired neural activity recording or response metric."),
            "behavior": measured("Rolling escape is the intended assay readout; protocol abstract does not supply a new quantified validation cohort", URL["S090"], "Abstract, final sentences"),
            "pain_boundary": boundary("Optogenetically elicited rolling is an assay of protective behavior, not a direct subjective-pain readout.", URL["S090"], "Abstract"),
        },
    },
    review_entry("S152", "Larval nociceptive circuit and behavioral assays are summarized"),
]


def update_access(source: dict, *, url: str, exact_url: bool) -> None:
    source["evidence"]["access_status"] = "open"
    source["field_resolution"]["evidence.access_status"] = {
        "state": "reported", "value": "open", "reason": "Primary publisher or institutional repository provides an open full text.",
        "checked_at": DATE, "locators": [{"url": url, "locator": "Full text or institutional thesis file listing"}],
    }
    if exact_url:
        source["identifiers"]["exact_url"] = url
        source["field_resolution"]["identifiers.exact_url"] = {
            "state": "reported", "value": url, "reason": "Institutional repository identifies the deposited doctoral thesis.",
            "checked_at": DATE, "locators": [{"url": url, "locator": "dc.identifier.uri and file listing"}],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit_path = DATA / "drosophila-nociception-audit.json"
    records_path = DATA / "records.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    records = json.loads(records_path.read_text(encoding="utf-8"))
    existing = {item["source_id"] for item in audit["entries"]}
    if existing & {item["source_id"] for item in EXTRA}:
        raise ValueError("audit extension already applied")
    audit["entries"].extend(EXTRA)
    audit["entries"].sort(key=lambda item: int(item["source_id"][1:]))
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["remaining_source_ids"] = ["S212", "S282"]
    audit["meta"]["remaining_primary_access"] = [
        {
            "source_id": "S212",
            "url": "https://www.biorxiv.org/content/10.1101/2025.09.25.678485v1.full",
            "checked_at": DATE,
            "result": "Primary full-text fetch failed in the current environment; indexed abstract on Sciety is secondary and does not establish exact stimulation or behavioral protocol.",
            "next": "Find author-deposited manuscript or regain primary bioRxiv full-text access.",
        },
        {
            "source_id": "S282",
            "url": "https://www.biorxiv.org/content/10.1101/2025.09.30.679458v1.full",
            "checked_at": DATE,
            "result": "Primary full-text fetch failed in the current environment; official bioRxiv archive lists title and DOI only, while the ResearchGate page offers no file.",
            "next": "Find author-deposited manuscript or regain primary bioRxiv full-text access.",
        },
    ]
    sources = {source["id"]: source for source in records["sources"]}
    for source_id in ("S012", "S152"):
        update_access(sources[source_id], url=URL[source_id], exact_url=False)
    update_access(sources["S013"], url=URL["S013"], exact_url=True)
    if not args.apply:
        print(json.dumps({"would_add": [item["source_id"] for item in EXTRA], "remaining": audit["meta"]["remaining_source_ids"]}))
        return 0
    snapshot = snapshot_repository(DATA, label="pre-drosophila-nociception-audit-extension")
    atomic_write_json(audit_path, audit)
    atomic_write_json(records_path, records)
    completeness_path = DATA / "completeness-report.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    atomic_write_json(completeness_path, completeness)
    print(json.dumps({"snapshot": str(snapshot), "records_count": len(audit["entries"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
