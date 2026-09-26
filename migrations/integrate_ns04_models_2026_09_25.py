"""Index two published NS-04 model studies without expanding their claims."""

# ruff: noqa: E501 -- precise source locators and caveats are intentionally long.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
SOURCES = {
    "S782": ("PMC13314972", "10.1038/s41467-026-72152-x"),
    "S783": ("PMC11446846", "10.1038/s41586-024-07854-7"),
}


def field(state: str, value: str | None, source_id: str, locator: str, reason: str) -> dict:
    pmcid, _ = SOURCES[source_id]
    return {
        "state": state, "value": value, "reason": reason, "checked_at": DATE,
        "locators": [{"url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", "locator": locator}],
    }


def entry(source_id: str) -> dict:
    if source_id == "S782":
        return {
            "source_id": source_id,
            "extraction": {
                "connectome_version": field("not_reported", None, source_id, "Methods > Connectome analysis; Supplementary Figure 7G-H", "The checked model paper does not pin an immutable release for every source graph. MANC v1.2.1 is named for a supplementary VNC analysis, not for S740's processed MANC matrix."),
                "organism_sex_stage": field("reported", "Drosophila melanogaster; adult connectome and separate adult experimental flies; sex is assay-specific", source_id, "Methods > Connectome analysis and Fly stocks", "Adult stage is explicit; do not infer the sex of all experimental cohorts from a single graph."),
                "dynamic_model": field("reported", "Connectome-derived leaky-integrator network with fitted cell-type dynamics, synaptic weights and motor decoders", source_id, "Results > Simulating a connectome-derived antennal grooming network; Methods > Model parameters and training", "The primary methods specify network dynamics and fitting."),
                "experimental_comparator": field("reported", "Optogenetic JO-F stimulation and measured head/antenna kinematics, with a held-out test dataset", source_id, "Results > Simulating a connectome-derived antennal grooming network; Figure 5A-B", "The comparison is with fly kinematics, not human pain outcomes."),
                "scope_boundary": field("reported", "Antenna/head grooming coordination in adult flies; no nociception, subjective pain, ECAP or SCS", source_id, "Abstract; Results > Simulating a connectome-derived antennal grooming network", "The measured target is movement coordination."),
            },
        }
    return {
        "source_id": source_id,
        "extraction": {
            "connectome_version": field("not_reported", None, source_id, "Methods > Connectome-constrained modelling and Identification of neurons in connectome", "The checked paper refers to FlyWire connectivity but does not pin the immutable graph release used by its model."),
            "organism_sex_stage": field("reported", "Drosophila melanogaster; adult FlyWire brain graph and separate adult experimental flies", source_id, "Abstract; Methods > Fly husbandry and Identification of neurons in connectome", "Specimen and experimental cohorts must not be collapsed into one animal."),
            "dynamic_model": field("reported", "Brian2 leaky integrate-and-fire spiking network with FlyWire synapse counts and predicted neurotransmitter signs", source_id, "Methods > Connectome-constrained modelling", "The primary methods give the software version and model construction."),
            "experimental_comparator": field("reported", "Targeted optogenetic silencing/stimulation, calcium imaging and walking/halting behavior in separate fly assays", source_id, "Results > Figure 3 and Figure 5; Methods > fly imaging and behavioral assays", "Circuit predictions are compared with experimental fly measurements."),
            "scope_boundary": field("reported", "Walk-OFF and brake mechanisms during feeding/grooming; no nociception, subjective pain, human ECAP or SCS", source_id, "Abstract; Results > Figure 5; Discussion", "Fly motor control is the studied target."),
        },
    }


def updated() -> tuple[dict, dict, dict, dict]:
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ns04-perturbation-model-audit.json").read_text(encoding="utf-8"))
    connectome = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    records = {item["id"]: item for item in json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]}
    if not all(records.get(sid, {}).get("identifiers", {}).get("doi") == doi for sid, (_, doi) in SOURCES.items()):
        raise ValueError("Published source DOI mismatch")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-04")
    if stream["source_ids"] != ["S775"] or {item["doi"] for item in audit["unindexed_primary_leads"]} != {doi for _, doi in SOURCES.values()}:
        raise ValueError("NS-04 initial screen has changed")
    if any(item["source_id"] in SOURCES for item in connectome["entries"]):
        raise ValueError("Already integrated")
    stream["source_ids"] = ["S775", "S782", "S783"]
    stream["coverage_note"] = "S775, S782 and S783 have primary full-text cards for fly connectome dynamics with optogenetic or behavioral comparison. Exact/synonym/author searches, full backward/forward citation snowballing and a later dated update remain open. None measures human pain, ECAP or SCS outcome."
    audit["catalogued_source_ids"] = stream["source_ids"]
    audit["unindexed_primary_leads"] = []
    audit["remaining"] = ["Complete exact/synonym/author searches", "Backward and forward citation snowballing", "Later dated update"]
    connectome["entries"].extend(entry(sid) for sid in SOURCES)
    connectome["meta"]["records_count"] = len(connectome["entries"])
    connectome["meta"]["generated_at"] = DATE
    matrix["rows"].append({
        "batch_id": "ns04-model-perturbation-primary-2026-09-25",
        "claim": "Two further connectome-derived adult fly dynamics studies compare model behavior or neural recruitment with targeted optogenetic and behavioral observations.",
        "target_variable": "antennal grooming kinematics and context-specific walking halt",
        "population_or_data": "Adult Drosophila connectomes and separate optogenetic/behavioral fly cohorts",
        "source_ids": ["S782", "S783"],
        "verified_evidence": "S782 Nature full text Figure 5 and Methods specify leaky-integrator model and held-out fly kinematic test. S783 Nature full text Figure 5 and Methods specify Brian2 spiking network and targeted fly imaging/behavioral assays.",
        "limitations": "Different behavioral targets and model structures; not independent replications of one clinical mechanism. No nociceptive subjective pain, human ECAP or SCS outcome. Exact graph releases remain unresolved in checked texts.",
        "permitted_conclusion": "Use as adult-fly connectome model and biological perturbation comparators only.",
        "locators": [
            {"source_id": sid, "url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", "locator": "Results > Figure 5; Methods > connectome-constrained model and fly assays"}
            for sid, (pmcid, _) in SOURCES.items()
        ],
    })
    return protocol, audit, connectome, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = updated()
    if not args.apply:
        print("Dry run: index S782/S783 in NS-04, connectome audit and evidence matrix")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns04-model-integration")
    for name, payload in zip(("search-protocol.json", "ns04-perturbation-model-audit.json", "drosophila-connectome-audit.json", "evidence-matrix.json"), outputs, strict=True):
        atomic_write_json(DATA / name, payload)
    print(f"Integrated S782/S783; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
