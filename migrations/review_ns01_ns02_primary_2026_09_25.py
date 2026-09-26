"""Link the primary FANC, MANC and Shiu cards to connectome prior art."""

# ruff: noqa: E501 -- primary source boundaries and locators are intentionally explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
FANC = "https://www.nature.com/articles/s41586-024-07389-x"
MANC = "https://elifesciences.org/reviewed-preprints/97769"
SHIU = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11446845/fullTextXML"


def field(state: str, value: str | None, reason: str, url: str, section: str) -> dict:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": url, "locator": section}],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    search = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if {"S773", "S774", "S775"} & {x["source_id"] for x in audit["entries"]}:
        raise ValueError("New connectome sources already audited")
    relation = next(x for x in records["sources"] if x["id"] == "S732")["relations"][0]
    if relation["external_id"] != "doi:10.1038/s41586-024-07763-9":
        raise ValueError("S732 relation changed")
    relation.update(target_id="S775", external_id=None)

    audit["entries"].extend(
        [
            {
                "source_id": "S773",
                "extraction": {
                    "connectome_version": field("not_reported", None, "The accessible publisher abstract and Data availability name FANC but do not pin an immutable source-connectome/CAVE release or the export used by S740.", FANC, "Abstract; Data availability; full Methods subscription notice"),
                    "organism_sex_stage": field("reported", "Drosophila melanogaster; female; adult ventral nerve cord", "The specimen identity is explicit in the abstract.", FANC, "Abstract"),
                    "dynamic_model": field("not_applicable", None, "The paper reconstructs anatomy and motor targets; it does not report a dynamical connectome model.", FANC, "Abstract; Figures 1–6 captions"),
                    "experimental_comparator": field("reported", "Genetic motor-neuron drivers and X-ray holographic nanotomography map muscle targets; these are anatomical comparators, not tests of a dynamical model.", "The abstract describes independent motor-target mapping.", FANC, "Abstract; Figures 3–6 captions"),
                    "scope_boundary": field("reported", "Adult female VNC anatomy and take-off motor circuits; no nociceptive subjective pain or human ECAP/SCS outcome", "The study endpoint is anatomical/motor circuit mapping.", FANC, "Abstract"),
                },
            },
            {
                "source_id": "S774",
                "extraction": {
                    "connectome_version": field("not_reported", None, "The full eLife Reviewed Preprint v1 names the neuPrint dataset MANC but does not identify the immutable export version underlying S740's processed matrix.", MANC, "Results > Overview of the VNC connectome; Data availability"),
                    "organism_sex_stage": field("reported", "Drosophila melanogaster; male; adult, five days old", "The methods identify the EM specimen.", MANC, "Methods > EM sample preparation"),
                    "dynamic_model": field("not_applicable", None, "This is the connectome reconstruction, not a neural dynamics model.", MANC, "Abstract; Results"),
                    "experimental_comparator": field("not_applicable", None, "The primary result is EM anatomy; no matched dynamical-model experimental comparator is reported.", MANC, "Abstract; Results"),
                    "scope_boundary": field("reported", "Male adult VNC anatomical dataset; S740 simulation input release and human ECAP/SCS transfer remain unverified", "Dataset identity does not establish another paper's processed input provenance.", MANC, "Data availability; Discussion"),
                },
            },
            {
                "source_id": "S775",
                "extraction": {
                    "connectome_version": field("not_reported", None, "The checked Nature JATS identifies the adult FlyWire graph but does not state an immutable graph release; versions from other FlyWire analyses cannot be imputed.", SHIU, "Abstract; Methods > Computational model; Data availability"),
                    "organism_sex_stage": field("reported", "Drosophila melanogaster; adult central-brain graph; experimental fly sex varies by assay", "The article and methods identify adult brain and female behavioral/imaging cohorts without a single graph specimen-sex assertion here.", SHIU, "Abstract; Methods > fly assays"),
                    "dynamic_model": field("reported", "Brainwide leaky integrate-and-fire model with alpha-synapse dynamics, connectome weights and neurotransmitter identity", "The full methods define the equations and parameters.", SHIU, "Methods > Computational model; Neurotransmitter predictions"),
                    "experimental_comparator": field("reported", "Optogenetic stimulation and fly neural/behavioral assays test scoped feeding and antennal-grooming circuit predictions", "The article tests model hypotheses in experimental flies.", SHIU, "Abstract; Results > feeding and grooming; Methods > fly assays"),
                    "scope_boundary": field("reported", "Central-brain feeding and grooming model; no VNC walking, nociceptive subjective pain, human ECAP or SCS outcome", "The authors warn that absolute simulated firing rates are unreliable.", SHIU, "Methods > Computational modelling limitations"),
                },
            },
        ]
    )
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["generated_at"] = DATE
    for stream_id, ids in [("NS-01", ["S773", "S774"]), ("NS-02", ["S775"])]:
        stream = next(x for x in search["search_streams"] if x["id"] == stream_id)
        stream["source_ids"].extend(ids)
        stream["coverage_note"] = (
            "Primary connectome/data or dynamics comparator cards were added on 2026-09-25; "
            "backward and forward citation screening and a later dated refresh remain open."
        )
    matrix["rows"].extend(
        [
            {
                "batch_id": "ns01-ns02-primary-refresh-2026-09-25",
                "claim": "FANC and MANC are primary adult female and male VNC anatomical resources, respectively.",
                "target_variable": "VNC connectome anatomy and motor-target mapping",
                "population_or_data": "S773 adult female FANC; S774 five-day-old male MANC EM specimen",
                "source_ids": ["S773", "S774"],
                "verified_evidence": "Nature S773 abstract and Data availability identify female VNC reconstruction and motor atlas; eLife S774 full text identifies male MANC reconstruction and neuPrint dataset.",
                "limitations": "Neither primary article pins the immutable exported input used by S740. S773 full methods were subscription gated during this pass. These resources do not validate a dynamic pain or human SCS model.",
                "permitted_conclusion": "Use as anatomical source descriptors and sex/stage comparators, with S740 matrix release still unresolved.",
                "locators": [
                    {"source_id": "S773", "url": FANC, "locator": "Abstract; Data availability"},
                    {"source_id": "S774", "url": MANC, "locator": "Results > Overview of the VNC connectome; Data availability"},
                ],
            },
            {
                "batch_id": "ns01-ns02-primary-refresh-2026-09-25",
                "claim": "A whole-brain FlyWire leaky integrate-and-fire model produced experimentally tested feeding and grooming circuit predictions.",
                "target_variable": "fly sensorimotor neural and behavioral responses",
                "population_or_data": "Adult Drosophila central-brain graph and separate fly experiments",
                "source_ids": ["S775"],
                "verified_evidence": "Nature full JATS Abstract, Results and Computational model describe the graph-constrained dynamics and scoped optogenetic/behavioral comparisons.",
                "limitations": "Graph release is not pinned in the checked JATS. Model omits morphology, receptor dynamics, gap junctions, peptides and neuromodulation; absolute firing rates are cautioned against. No nociceptive pain, ECAP or SCS endpoint.",
                "permitted_conclusion": "Use as fly connectome-dynamics and biological-comparator prior art only.",
                "locators": [{"source_id": "S775", "url": SHIU, "locator": "Abstract; Results; Methods > Computational model and limitations"}],
            },
        ]
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns01-ns02-primary-audit")
        for name, payload in [
            ("records.json", records),
            ("drosophila-connectome-audit.json", audit),
            ("search-protocol.json", search),
            ("evidence-matrix.json", matrix),
        ]:
            atomic_write_json(DATA / name, payload)
        print(f"Applied NS-01/NS-02 primary review; snapshot: {snapshot}")
    else:
        print("Dry run: three primary cards linked; citation snowballing remains open")


if __name__ == "__main__":
    main()
