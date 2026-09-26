"""Start source-resolved Drosophila nociception measurement audit."""

# ruff: noqa: E501 -- exact primary-source locators and extraction statements are retained.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"


def measured(value: str, url: str, locator: str) -> dict:
    return {
        "state": "reported", "value": value, "reason": "Directly described by the primary source.",
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


def absent(state: str, reason: str, url: str, locator: str) -> dict:
    return {
        "state": state, "value": None, "reason": reason,
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


def boundary(value: str, url: str, locator: str) -> dict:
    item = measured(value, url, locator)
    item["reason"] = (
        "Conservative inference from the primary measurements; the source does not "
        "directly measure subjective experience."
    )
    return item


SOURCES = {
    "S026": "https://www.jstage.jst.go.jp/article/hikakuseiriseika/31/4/31_151/_pdf",
    "S027": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9934396/",
    "S029": "https://pubmed.ncbi.nlm.nih.gov/41280033/",
    "S030": "https://www.nature.com/articles/nn.4580",
    "S065": "https://elifesciences.org/reviewed-preprints/110557",
    "S092": "https://elifesciences.org/articles/95379",
    "S154": "https://www.mdpi.com/2306-5729/10/2/11",
}

ENTRIES = [
    {
        "source_id": "S026",
        "extraction": {
            "stimulus": measured("44 °C noxious heat applied to decapitated adult flies", SOURCES["S026"], "Meeting abstract, p. 160, stimulus and preparation"),
            "neural_response": absent("not_reported", "Meeting abstract gives no neural recording or neural response metric.", SOURCES["S026"], "Meeting abstract, p. 160"),
            "behavior": measured("Tumbling protective response; sample size and effect size absent from the short abstract", SOURCES["S026"], "Meeting abstract, p. 160, result"),
            "pain_boundary": boundary("The observed tumbling is nocifensive behavior in a decapitated preparation, not evidence of subjective pain.", SOURCES["S026"], "Meeting abstract, p. 160, assay description"),
        },
    },
    {
        "source_id": "S027",
        "extraction": {
            "stimulus": measured("Capsaicin delivered to transgenic human-TRPV1 nociceptors: 20 mM brush exposure in larvae and 5 mM capsaicin food in adults", SOURCES["S027"], "Results, larval brush and adult feeding assays; Supporting information S1-S2 Videos"),
            "neural_response": absent("not_reported", "Transgenic receptor activation is inferred from the assay; no matched neural activity recording establishes a stimulus-evoked response.", SOURCES["S027"], "Results, capsaicin assays"),
            "behavior": measured("Larval rolling and adult nocifensive feeding responses, plus drug-modulated behavioral and survival outcomes", SOURCES["S027"], "Results, larval and adult capsaicin assays"),
            "pain_boundary": boundary("The paper calls the model pain, but capsaicin-dependent protective and survival outcomes do not measure subjective pain.", SOURCES["S027"], "Abstract and Results, behavioral assays"),
        },
    },
    {
        "source_id": "S029",
        "extraction": {
            "stimulus": measured("Thermal nociceptive stimulation above 40 °C and optogenetic activation of adult abdominal multidendritic neurons", SOURCES["S029"], "Abstract; Figure 1, optogenetic screen"),
            "neural_response": measured("Calcium imaging of abdominal multidendritic axons shows activation by thermal nociceptive stimuli; connectomic reconstruction identifies ascending partners", SOURCES["S029"], "Abstract, calcium imaging and connectomic reconstruction"),
            "behavior": measured("Rapid escape and sustained place avoidance; distinct ascending classes contribute to these outcomes", SOURCES["S029"], "Abstract; Figure 1, place aversion and locomotion"),
            "pain_boundary": boundary("Dedicated nociceptors, ascending pathways and avoidance are objective criteria; they do not directly measure subjective experience.", SOURCES["S029"], "Abstract, final two sentences"),
        },
    },
    {
        "source_id": "S030",
        "extraction": {
            "stimulus": measured("Noxious mechanical and thermal stimuli in Drosophila larvae, with optogenetic circuit perturbation", SOURCES["S030"], "Abstract, first and third sentences"),
            "neural_response": measured("Trans-synaptic labeling, ultrastructure and calcium imaging identify a mechanonociceptive integration circuit and neuropeptide feedback", SOURCES["S030"], "Abstract, Methods summary and final sentences"),
            "behavior": measured("Modality-specific larval escape response; mechanonociceptive circuit is not required for thermonociceptive escape", SOURCES["S030"], "Abstract, circuit-specific result"),
            "pain_boundary": boundary("Larval escape is a nocifensive behavioral output, separate from circuit activity and subjective pain.", SOURCES["S030"], "Abstract, stimulus and escape description"),
        },
    },
    {
        "source_id": "S065",
        "extraction": {
            "stimulus": measured("473 nm, 10 mW laser directed to ventral thorax of adult male flies during a 180 s assay", SOURCES["S065"], "Results, Automated laser-based nociception assay; Methods, Nociception-induced escape assay"),
            "neural_response": absent("not_reported", "Kir2.1 silencing and trans-Tango tracing support circuit involvement, but no stimulus-evoked neural activity is reported for the proposed pathway.", SOURCES["S065"], "Results, tracing and silencing; Discussion, limits of anatomical labeling"),
            "behavior": measured("Latency to first escape jump, with baseline walking velocity used to monitor locomotor confounding", SOURCES["S065"], "Results, Automated laser-based nociception assay"),
            "pain_boundary": boundary("Escape latency after noxious heat is behavior; tracing and silencing do not establish a subjective pain measure.", SOURCES["S065"], "Discussion, limitations and circuit interpretation"),
        },
    },
    {
        "source_id": "S092",
        "extraction": {
            "stimulus": measured("Mechanical radial stretch and experimental epidermal-cell stimulation in Drosophila larvae", SOURCES["S092"], "Abstract; Results, Epidermal cells are intrinsically mechanosensitive"),
            "neural_response": measured("Epidermal GCaMP6s calcium responses to stretch and activation of somatosensory neurons including nociceptors", SOURCES["S092"], "Abstract; Results, stretch-evoked calcium responses"),
            "behavior": measured("Larval avoidance and escape plus increased sensitivity to subsequent mechanical stimulation", SOURCES["S092"], "Abstract, final three sentences"),
            "pain_boundary": boundary("Epidermal and sensory calcium signals plus protective behavior establish nociceptive sensitivity, not subjective pain.", SOURCES["S092"], "Abstract and Results"),
        },
    },
    {
        "source_id": "S154",
        "extraction": {
            "stimulus": measured("Ultraviolet injury or sham injury in third-instar Drosophila larvae", SOURCES["S154"], "Abstract; Section 2.1 Background and Summary"),
            "neural_response": absent("not_applicable", "This data descriptor sequences ribosome-bound nociceptor RNA; it does not measure evoked electrical or calcium activity.", SOURCES["S154"], "Abstract; Section 2.1 and Data Description"),
            "behavior": absent("not_applicable", "The deposited translatome compares pooled UV-injured and sham-injured larvae; no behavioral outcome is measured in this dataset.", SOURCES["S154"], "Abstract; Data Description"),
            "pain_boundary": boundary("Nociceptor translatomic change is a molecular injury response, not a behavioral or subjective-pain outcome.", SOURCES["S154"], "Abstract and Data Description"),
        },
        "other_readout": "Class-IV nociceptor ribosome-bound RNA sequencing, BioProject PRJNA1056042",
    },
]

STAGES = {
    "S012": ("mixed", "Drosophila melanogaster", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8996152/", "Review, larval and adult assay sections"),
    "S027": ("mixed", "Drosophila melanogaster", SOURCES["S027"], "Results, larval capsaicin brush and adult feeding assays"),
    "S065": ("drosophila_adult", "Drosophila melanogaster", SOURCES["S065"], "Results, adult male assay; Methods, Fly strains and husbandry"),
    "S152": ("drosophila_larva", "Drosophila melanogaster", "https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1076017/full", "Title and Abstract, larval nociception review"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records_path = DATA / "records.json"
    audit_path = DATA / "drosophila-nociception-audit.json"
    if audit_path.exists():
        raise ValueError("audit already exists")
    records = json.loads(records_path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in records["sources"]}
    for source_id, (domain, species, url, locator) in STAGES.items():
        source = sources[source_id]
        source["evidence"]["subject_domain"] = domain
        source["evidence"]["species"] = species
        for field_name, value in (("evidence.subject_domain", domain), ("evidence.species", species)):
            source["field_resolution"][field_name] = {
                "state": "reported", "value": value,
                "reason": "Primary source identifies the reviewed or experimental Drosophila life stage.",
                "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
            }
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    candidate_ids = next(stream["source_ids"] for stream in protocol["search_streams"] if stream["id"] == "NS-03")
    remaining = [source_id for source_id in candidate_ids if source_id not in {entry["source_id"] for entry in ENTRIES}]
    audit = {
        "meta": {
            "schema_version": "1.0.0", "generated_at": DATE,
            "status": "in_progress", "records_count": len(ENTRIES),
            "scope": "Primary measurement extraction for NS-03 Drosophila nociception candidates",
            "candidate_source_ids": candidate_ids,
            "remaining_source_ids": remaining,
            "unindexed_primary_leads": next(stream["unindexed_primary_leads"] for stream in protocol["search_streams"] if stream["id"] == "NS-03"),
        },
        "construct_boundary": "Stimulus, neural activity or molecular response, and protective behavior are separate observations; none directly measures subjective pain or establishes human transfer.",
        "entries": ENTRIES,
    }
    if not args.apply:
        print(json.dumps({"would_add": [entry["source_id"] for entry in ENTRIES], "remaining": remaining}))
        return 0
    snapshot = snapshot_repository(DATA, label="pre-drosophila-nociception-core-review")
    atomic_write_json(records_path, records)
    atomic_write_json(audit_path, audit)
    completeness_path = DATA / "completeness-report.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    atomic_write_json(completeness_path, completeness)
    print(json.dumps({"snapshot": str(snapshot), "records_count": len(ENTRIES), "remaining": remaining}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
