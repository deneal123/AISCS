"""Add the two published larval nociception sources to the NS-03 audit."""

# ruff: noqa: E501 -- keep exact primary-source extraction statements readable.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
NATURE = "https://www.nature.com/articles/s41467-023-42202-9"
ELIFE = "https://elifesciences.org/articles/26016v2"


def field(value: str, url: str, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": "reported",
        "value": value,
        "reason": (
            "Conservative inference from source scope; subjective experience is not directly measured."
            if boundary else "Directly described by the primary source."
        ),
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


NEW_ENTRIES = [
    {
        "source_id": "S760",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field(
                "Third-instar larvae: optogenetic C4da activation, noxious heat and mechanical stimulation; glucose feeding perturbs the internal state.",
                NATURE, "Results, Figures 1-2: C4da activation, thermal and mechanical rolling assays",
            ),
            "neural_response": field(
                "Descending GABAergic neurons suppress C4da presynaptic calcium activity through GABA-B signaling; neural activity is distinct from the rolling readout.",
                NATURE, "Abstract; Results, Figures 3-4: C4da calcium imaging and GABA-B receptor tests",
            ),
            "behavior": field(
                "Larval rolling probability, duration and onset latency are measured after noxious or optogenetic stimulation; descending-neuron manipulation changes these outcomes.",
                NATURE, "Results, Figure 2 and legend: rolling duration, probability and latency",
            ),
            "pain_boundary": field(
                "C4da responses and rolling demonstrate nociceptive gating in larvae, without directly measuring subjective pain or human clinical transfer.",
                NATURE, "Abstract and Discussion", boundary=True,
            ),
        },
    },
    {
        "source_id": "S761",
        "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field(
                "Larval noxious heat and optogenetic activation of nociceptors or DnB interneurons.",
                ELIFE, "Results, Figures 1-3: heat and optogenetic activation assays",
            ),
            "neural_response": field(
                "DnB interneurons respond to noxious heat; EM reconstruction links sensory input to DnB and Goro, while calcium imaging measures DnB and Goro activity.",
                ELIFE, "Abstract; Results, Figures 3 and 6: DnB and Goro imaging and circuit reconstruction",
            ),
            "behavior": field(
                "Nocifensive escape comprises body bending and rolling; Goro inactivation blocks DnB-induced rolling while leaving bending intact.",
                ELIFE, "Abstract; Results, DnBs promote rolling but not C-bending through Goro network",
            ),
            "pain_boundary": field(
                "Circuit activity, body bending and rolling are distinct measured outcomes; the study does not directly measure subjective pain or human transfer.",
                ELIFE, "Abstract and Discussion", boundary=True,
            ),
        },
    },
]


def update() -> dict:
    protocol_path = DATA / "search-protocol.json"
    audit_path = DATA / "drosophila-nociception-audit.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-03")
    if {entry["source_id"] for entry in audit["entries"]} & {"S760", "S761"}:
        raise ValueError("New sources already audited")
    if len(stream["unindexed_primary_leads"]) != 2:
        raise ValueError("Expected two pending primary leads")
    if set(audit["meta"]["remaining_source_ids"]) != {"S212", "S282"}:
        raise ValueError("Unexpected unresolved candidate set")
    lead_ids = {"S760", "S761"}
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    if not lead_ids <= {record["id"] for record in records["sources"]}:
        raise ValueError("Canonical source cards must be published first")
    resolved = [
        {**lead, "source_id": source_id, "status": "primary_full_text_canonical_card_and_audit_recorded"}
        for lead, source_id in zip(stream["unindexed_primary_leads"], ("S760", "S761"), strict=True)
    ]
    stream["source_ids"] = sorted([*stream["source_ids"], *lead_ids])
    stream["unindexed_primary_leads"] = []
    stream["indexed_primary_leads"] = resolved
    stream["coverage_note"] = (
        "Seventeen canonical candidates include original experiments, protocols, a dataset description and reviews; "
        "these evidence roles are screened separately. Fifteen candidates have source-specific stimulus, neural-response, "
        "behavior and pain-boundary extraction; S212 and S282 await primary full text."
    )
    audit["entries"].extend(NEW_ENTRIES)
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["candidate_source_ids"] = stream["source_ids"]
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["unindexed_primary_leads"] = []
    audit["meta"]["indexed_primary_leads"] = resolved
    return {"protocol": protocol, "audit": audit}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    updated = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns03-new-source-audit")
        atomic_write_json(DATA / "search-protocol.json", updated["protocol"])
        atomic_write_json(DATA / "drosophila-nociception-audit.json", updated["audit"])
        print(f"Applied NS-03 audit extension; snapshot: {snapshot}")
    else:
        print("Dry run: 17 candidates, 15 audited, 2 awaiting primary full text")


if __name__ == "__main__":
    main()
