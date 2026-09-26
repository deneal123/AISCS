"""Reconcile the core Drosophila connectome and VNC evidence."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
AUDIT = "drosophila-connectome-audit.json"
BATCH = "drosophila-connectome-core-2026-09-24"

# State, value, exact section locator. An absent method or comparator is terminal,
# rather than inferred from a different paper or a similarly named connectome.
SPECS: dict[str, dict[str, Any]] = {
    "S068": {
        "url": "https://www.nature.com/articles/s41586-024-07982-0",
        "population": "Adult female Drosophila FlyWire brain connectome; simulations on 121,327 connected neurons",
        "dataset": "FlyWire FAFB v783 whole-brain connectome, thresholded to 121,327 connected neurons for simulation",
        "method": "Signed connectome-weighted whole-brain simulation and instrumental-variable effectome estimator",
        "notes": "The paper proposes optogenetic perturbation as an experimental route to the effectome, while its estimator is tested against simulated ground truth. The 121,327 neurons are a thresholded simulation graph, not a count of recorded animals or a biological dynamics comparator. No nociception, ECAP or SCS endpoint.",
        "evidence": {"species": "Drosophila melanogaster", "subject_domain": "simulation", "access_status": "open"},
        "dimensions": {
            "connectome_version": ("reported", "FlyWire FAFB v783", "Methods, connectome data: most recent version v783; author-deposited full text"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; female; adult brain", "Methods, FlyWire/FAFB connectome identity"),
            "dynamic_model": ("reported", "Signed synapse-count-weighted whole-brain linear and rectified simulations with 121,327 connected neurons", "Fig. 3 and simulation Methods"),
            "experimental_comparator": ("not_applicable", None, "Fig. 3: estimator compared with simulated ground truth; optogenetic perturbation is proposed, not a matched new biological validation"),
            "scope_boundary": ("reported", "Causal effectome estimation feasibility and simulation, not observed fly pain or human SCS", "Abstract, Fig. 3 and Discussion"),
        },
    },
    "S106": {
        "url": "https://www.nature.com/articles/s41592-021-01330-0",
        "population": "Adult female Drosophila FAFB electron-microscopy brain volume",
        "dataset": "FAFB adult female brain EM volume in the early FlyWire proofreading platform; no later v783 release asserted",
        "method": "Collaborative web-based proofreading and reconstruction of EM-derived neural circuits",
        "notes": "FlyWire platform paper published before the later v783 release. It demonstrates proofreading and connectivity analysis in an adult female brain; it is neither a VNC dataset nor a biological neural-dynamics, nociception, ECAP or SCS validation.",
        "evidence": {"subject_domain": "drosophila_adult", "modalities": ["connectome"]},
        "dimensions": {
            "connectome_version": ("not_reported", None, "Main and Methods: early FlyWire/FAFB platform paper does not identify a frozen v783-style release for the analyzed proofread state"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; female; adult brain", "Introduction and Methods, FAFB EM volume"),
            "dynamic_model": ("not_applicable", None, "Abstract and Methods: proofreading platform and connectivity diagram, not a dynamical simulation"),
            "experimental_comparator": ("not_applicable", None, "Abstract and Results: no model-versus-biological activity comparator"),
            "scope_boundary": ("reported", "Brain-connectomics platform and circuit anatomy; no VNC or pain/SCS endpoint", "Abstract and Discussion"),
        },
    },
    "S219": {
        "url": "https://codex.flywire.ai/api/download?data_version=783",
        "population": "One adult female Drosophila melanogaster brain (FAFB); central brain and optic lobes, not VNC",
        "dataset": "FlyWire FAFB v783 adult female brain connectome",
        "method": "Static synapse-resolution brain connectome resource; no dynamical model in this dataset record",
        "notes": "FAFB v783 is a single adult female brain resource, not a VNC or a behavioural or neural-dynamics experiment. Do not infer clinical pain or SCS outcomes from connectivity alone.",
        "dimensions": {
            "connectome_version": ("reported", "FlyWire FAFB v783", "download API data_version=783; compare BANC Methods, Semi-automated cell typing"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; female; adult; brain only", "BANC Nature Methods, Semi-automated cell typing: FAFB is a dense reconstruction of the female brain"),
            "dynamic_model": ("not_applicable", None, "FlyWire data download: static connectome resource, not a dynamical-model report"),
            "experimental_comparator": ("not_applicable", None, "FlyWire data download: no experimental model validation in this resource record"),
            "scope_boundary": ("reported", "Brain anatomy; no VNC, nociception, ECAP or clinical SCS endpoint", "FlyWire data download; BANC Nature Methods, Semi-automated cell typing"),
        },
    },
    "S286": {
        "url": "https://arxiv.org/html/2602.17997v3",
        "population": "Adult Drosophila brain connectome used as a controller for a simulated biomechanical fly",
        "dataset": "FlyWire adult-brain connectome; FAFB v783 is named for graph visualization, while the controller input release is not pinned",
        "method": "Fly-connectomic Graph Model: signed synaptic message passing trained by deep reinforcement learning for simulated locomotion",
        "notes": "arXiv v3. The work compares a connectome-derived controller with random, rewired and MLP controllers in simulated locomotion. FAFB v783 is identified in the visualization appendix, but an exact controller input release is not pinned. No direct biological neural or behavioural comparator, nociception, ECAP or SCS outcome.",
        "evidence": {"species": "Drosophila melanogaster", "subject_domain": "simulation", "target_construct": "not_applicable", "access_status": "open"},
        "dimensions": {
            "connectome_version": ("not_reported", None, "Method and Appendix D.1: FlyWire FAFB v783 is identified for visualization; the graph controller input release is not explicitly pinned"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; adult connectome; sex of controller input not independently specified", "Abstract and Method 3.1; Appendix D.1"),
            "dynamic_model": ("reported", "Signed connectome-derived message-passing graph controller trained by deep reinforcement learning", "Method 3.1-3.2 and Fig. 1"),
            "experimental_comparator": ("not_applicable", None, "Experiments 4.1-4.3 compare simulated random, rewired and MLP controllers; no biological recording or animal intervention test"),
            "scope_boundary": ("reported", "Virtual-fly locomotion and computational baseline comparisons; no biophysical brain dynamics or pain/SCS endpoint", "Abstract, Experiments and Conclusion"),
        },
    },
    "S738": {
        "url": "https://www.nature.com/articles/s41586-026-10735-w",
        "population": "One adult female Drosophila melanogaster central nervous system, brain and ventral nerve cord",
        "dataset": "BANC-FlyWire v888 brain-and-cord connectome; v888 v2 synapse table",
        "method": "Synapse-resolution reconstruction with graph connectivity and influence analyses",
        "notes": "BANC v888 is one adult female's brain-and-cord anatomy. Its graph influence analysis is not a calibrated biophysical dynamics model or an ECAP/SCS measurement operator; circuit comparisons are anatomical and functional context, not clinical validation.",
        "dimensions": {
            "connectome_version": ("reported", "BANC-FlyWire v888; v888 v2 synapse table", "Methods, Data availability and connectivity/influence analyses"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; female; adult; one CNS", "Abstract and Methods, BANC dataset"),
            "dynamic_model": ("not_applicable", None, "Methods, graph connectivity and influence analyses; no time-resolved biophysical CNS simulation is claimed"),
            "experimental_comparator": ("not_reported", None, "Methods, Semi-automated cell typing and circuit vignettes: anatomical cross-dataset comparison and prior experiments, without a matched prospective model-versus-recording test"),
            "scope_boundary": ("reported", "Whole brain and VNC anatomical connectome from one female; no nociception or human SCS outcome validation", "Abstract, Discussion and Methods"),
        },
    },
    "S739": {
        "url": "https://www.biorxiv.org/content/10.64898/2026.08.21.745055v1.full",
        "population": "Adult Drosophila brain connectome; calcium recordings from head-fixed flies",
        "dataset": "FlyWire v783 brain connectome; resting-state whole-brain calcium imaging",
        "method": "First-order rate dynamics on fixed connectome topology, fitted to deconvolved calcium-derived neuropil activity",
        "notes": "Preprint v1. FlyWire v783 constrains a resting-state rate model. Five independently trained models are model replicates, not five animals. The first half of each approximately 14-minute trace was used for fitting and the second half held out; no nociceptive, ECAP or clinical comparator.",
        "dimensions": {
            "connectome_version": ("reported", "FlyWire v783; model scaffold of 138,639 neurons and 15,091,983 chemical synapses", "Results, Fig. 1b and Connectome-constrained resting-state fitting"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; adult female connectome; head-fixed fly calcium data", "Introduction and Results, Fig. 1a-b; FAFB source identity"),
            "dynamic_model": ("reported", "First-order single-neuron rate equations with fixed topology/sign, fitted synaptic strengths and time constants", "Results, Fig. 1c-e; Methods Eq. 3"),
            "experimental_comparator": ("reported", "Whole-brain resting-state calcium recordings: deconvolved neuropil activity; later half of each trace held out", "Results, Fig. 1a,e-f and training paragraph"),
            "scope_boundary": ("reported", "Spontaneous neuropil activity; n=5 independently trained models, not flies; no nociception or SCS", "Results, Fig. 1 and paragraph following training description"),
        },
    },
    "S740": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13142387/",
        "population": "Adult Drosophila VNC connectomes across male and female datasets; decapitated flies for optogenetic test",
        "dataset": "Four adult VNC-containing datasets: male MANC, female FANC, male mCNS, female BANC",
        "method": "Dynamic VNC network simulation, descending-neuron activation screen and circuit pruning",
        "notes": "Preprint on walking CPGs. Four VNC-containing connectomes and both sexes support computational motif robustness. Optogenetic activation of DNb08 in decapitated flies tests a separate predicted pathway. This is a motor-circuit comparator, not nociception, ECAP or SCS validation.",
        "dimensions": {
            "connectome_version": ("not_reported", None, "Methods, VNC connectome datasets: MANC, FANC, mCNS and BANC are named, but release numbers for all four simulation inputs are not pinned"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; adult; both male and female VNC datasets", "Results, convergence across both sexes and four connectomes"),
            "dynamic_model": ("reported", "Dynamic VNC simulations; DNg100 screen and three-neuron E-E-I rhythm-generating circuit", "Abstract and Results, pruning screen"),
            "experimental_comparator": ("reported", "Optogenetic DNb08 activation in decapitated flies evoked rhythmic leg movements resembling searching, not coordinated walking", "Results, DNb08 optogenetic experiment and Fig. 5c-e"),
            "scope_boundary": ("reported", "Walking motor rhythm and a tested DNb08 pathway; does not validate pain, ECAP or SCS", "Abstract and Discussion"),
        },
    },
    "S744": {
        "url": "https://www.nature.com/articles/s41586-024-07939-3",
        "population": "Adult Drosophila visual system; 64 modeled cell types with published functional recordings",
        "dataset": "Compiled adult fly visual-system connectome; official flyvis scaffold fib25-fib19_v2.2.json; 64 cell types",
        "method": "Connectome-constrained deep mechanistic network with simplified neurons and synapses, optimized for visual motion",
        "notes": "The 64-cell-type visual network predicts measured single-neuron visual responses. The official flyvis implementation names the compiled scaffold fib25-fib19_v2.2.json; this is a constructed file, not a single FlyWire/BANC release. The endpoint is visual function, not VNC, nociception, ECAP or SCS.",
        "dimensions": {
            "connectome_version": ("reported", "Official flyvis compiled scaffold: fib25-fib19_v2.2.json; underlying local reconstructions are multiple sources", "Official flyvis documentation, Connectome from average local reconstructions, code comment naming data/connectome/fib25-fib19_v2.2.json"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster; adult visual system; sex of all functional comparator flies not resolved here", "Abstract, Main and Methods"),
            "dynamic_model": ("reported", "Deep mechanistic network with 45,669 neurons and 1,513,231 connections across 64 visual cell types", "Main, model construction and Fig. 1"),
            "experimental_comparator": ("reported", "Published single-neuron visual response measurements for identified cell types, including contrast and direction tuning", "Main, comparison of model predictions to measurements; Fig. 2"),
            "scope_boundary": ("reported", "Visual motion computation; no VNC, nociception, ECAP or clinical SCS comparator", "Abstract and Discussion"),
        },
    },
    "S743": {
        "url": "https://www.nature.com/articles/s41593-025-02080-4",
        "population": "Empirical connectivity examples from Drosophila larval premotor and adult central-complex circuits, plus larval zebrafish oculomotor circuit",
        "dataset": "Zarin et al. larval premotor; Scheffer et al. adult central complex; Vishwanathan et al. larval zebrafish connectomes",
        "method": "Teacher-student recurrent-network analysis with fixed connectome weights and uncertain single-neuron parameters",
        "notes": "Theory and simulation of neural-activity identifiability with empirical connectome topologies. The teacher network is simulated ground truth; observing a subset of teacher neurons is not a biological recording comparator for the inferred dynamics. No nociception, ECAP or SCS transfer is tested.",
        "dimensions": {
            "connectome_version": ("not_reported", None, "Data availability names Zarin, Scheffer and Vishwanathan source connectomes but does not pin release identifiers"),
            "organism_sex_stage": ("reported", "Drosophila melanogaster larva and adult; Danio rerio larva; sex not reported for all modeled circuits", "Data availability and Fig. 5 / Extended Data Fig. 4"),
            "dynamic_model": ("reported", "Teacher-student recurrent networks with shared synaptic weights and differing biophysical parameters", "Abstract and Results, teacher-student recurrent networks"),
            "experimental_comparator": ("not_applicable", None, "Abstract and Fig. 5: student activity is compared with simulated teacher ground truth, not directly with new biological recordings"),
            "scope_boundary": ("reported", "Identifiability theory for partial neural observation; not a fly pain, VNC motor or human SCS experiment", "Abstract and Discussion"),
        },
    },
}


def _audit() -> dict[str, Any]:
    entries = []
    for source_id, spec in SPECS.items():
        extraction = {}
        for name, (state, value, locator) in spec["dimensions"].items():
            url = spec["url"]
            if source_id == "S219" and name == "organism_sex_stage":
                url = "https://www.nature.com/articles/s41586-026-10735-w"
            if source_id == "S744" and name == "connectome_version":
                url = "https://github.com/TuragaLab/flyvis/blob/main/docs/docs/examples/01_flyvision_connectome.md"
            if source_id == "S068" and name == "connectome_version":
                url = "https://api.repository.cam.ac.uk/server/api/core/bitstreams/1b44c48c-2482-4148-b4e1-36c36c2c42a4/content"
            extraction[name] = {
                "state": state,
                "value": value,
                "reason": "Extracted from primary material." if state == "reported" else locator,
                "checked_at": DATE,
                "locators": [{"url": url, "locator": locator}],
            }
        entry: dict[str, Any] = {"source_id": source_id, "extraction": extraction}
        if source_id == "S740":
            revision = "10e7661bf414ba7b4c2edf795cd36d0f878c17c0"
            prefix = f"https://github.com/smpuglie/Pugliese_2026/blob/{revision}/"
            entry["input_matrix_artifacts"] = [
                {
                    "dataset": "MANC",
                    "matrix": "data/manc t1 connectome data/W_20250813_DNtoMN_unsorted.csv",
                    "config_url": prefix + "configs/experiment/DNg100_Stim.yaml",
                },
                {
                    "dataset": "FANC",
                    "matrix": "data/fanc t1l connectome data/W_BDN2toMN_20250107_corrected.npy",
                    "config_url": prefix + "configs/experiment/DNg100_Stim_FANC.yaml",
                },
                {
                    "dataset": "BANC",
                    "matrix_candidates": ["data/banc t1 premotor/W_20251217.npz", "data/banc t1 premotor/W_20260217.npz"],
                    "config_url": prefix + "notebooks/Figure%202.ipynb",
                    "locator": "Figure 2 notebook, BANC run_id=33241778; fallback wTable_20251217_fullData.csv. Repository data/banc t1 premotor also contains W_20251217.npz and W_20260217.npz; the notebook does not pin which W file generated the archived run.",
                },
            ]
            entry["input_matrix_note"] = "Author configs pin MANC/FANC matrix files. The Figure 2 notebook identifies a BANC run and fallback neuron table, while two BANC W files exist; its exact matrix choice remains unverified. Zenodo record 22260924 archives the mCNS simulation as DNg100_Stim_IMAC_vncOnly.zip but gives no mCNS source matrix/release. Matrix file dates and current FlyWire/neuPrint versions are not the releases used by these simulations."
            entry["simulation_archive"] = {
                "url": "https://zenodo.org/records/22260924",
                "locator": "Simulation catalog: DNg100_Stim_IMAC_vncOnly.zip and DNg100_Stim_BANC_vncOnly.zip; archived run configurations",
            }
        entries.append(entry)
    return {
        "meta": {"schema_version": "1.0.0", "generated_at": DATE, "records_count": len(entries), "gate": "G0_REVISE", "scope": "Primary whole-brain/cord connectome resources and connectome-constrained Drosophila model records", "selection_boundary": "Nociceptive circuit papers are reviewed under SRC-04; secondary commentary and code-only resources do not establish biological dynamics or comparators."},
        "construct_boundary": "Connectome anatomy, neural dynamics, motor behavior and visual responses are distinct. None directly measures subjective pain, human ECAP or SCS outcome.",
        "entries": entries,
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found = set()
    updated_sources = []
    for record in records["sources"]:
        source_id = record["id"]
        if source_id not in SPECS:
            updated_sources.append(record)
            continue
        spec = SPECS[source_id]
        record = deepcopy(record)
        record["метод"] = spec["method"]
        record["датасет"] = spec["dataset"]
        record["ограничения"] = spec["notes"]
        record["evidence"]["population"] = spec["population"]
        if source_id == "S219":
            record["evidence"]["subject_domain"] = "drosophila_adult"
            record["evidence"]["modalities"] = ["connectome"]
        if source_id == "S740":
            record["evidence"]["target_construct"] = "not_applicable"
            record["evidence"]["target_label"] = "Walking motor rhythm and DNb08-driven leg movement"
        record["evidence"].update(spec.get("evidence", {}))
        if source_id == "S286":
            record["validation"].update({"status": "verified_primary", "full_text_status": "checked"})
        record["validation"].update({"checked_at": DATE, "notes": spec["notes"]})
        record = migrate_record(record, checked_at=DATE)
        for path in ("метод", "датасет", "ограничения", "evidence.population", "evidence.subject_domain", "evidence.modalities", "evidence.target_construct", "evidence.target_label", "validation.notes"):
            if path in record["field_resolution"]:
                record["field_resolution"][path]["locators"] = [{"url": spec["url"], "locator": "Primary full text, Abstract/Methods/Results/Discussion; field " + path}]
        updated_sources.append(record)
        found.add(source_id)
    if found != set(SPECS):
        raise ValueError(f"missing sources: {sorted(set(SPECS) - found)}")
    records["sources"] = updated_sources
    records["meta"]["updated_at"] = DATE
    by_id = {x["id"]: x for x in updated_sources}
    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in SPECS:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
    clusters["meta"]["updated_at"] = DATE
    log = load_json(data_dir / "validation-log.json")
    log.setdefault("searches", []).append({"search_id": "CONNECTOME-CORE-2026-09-24-01", "date": DATE, "stream": "Drosophila connectome/VNC primary full-text re-extraction", "query": "exact title and version terms at publisher, PMC, bioRxiv and FlyWire", "urls_reviewed": [spec["url"] for spec in SPECS.values()], "source_ids": sorted(SPECS), "decision": "version, organism, dynamic model, experimental comparator and scope resolved in separate audit"})
    log["meta"]["checked_at"] = DATE
    report = load_json(data_dir / "audit-report.json")
    report["meta"]["generated_at"] = DATE
    report["current_corpus"]["validation_statuses"] = dict(sorted(Counter(x["validation"]["status"] for x in updated_sources).items()))
    report["drosophila_connectome_audit"] = {"checked_at": DATE, "source_ids": sorted(SPECS), "artifact": AUDIT, "finding": "Anatomy, dynamics and biological comparators explicitly separated."}
    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(updated_sources))
    completeness["meta"]["generated_at"] = DATE
    return {"records.json": records, "clusters.json": clusters, "validation-log.json": log, "audit-report.json": report, "completeness-report.json": completeness, AUDIT: _audit()}


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-connectome-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        result = validate_repository(target)
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-drosophila-connectome-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        result = validate_repository(DATA)
        if not result["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(result['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(SPECS), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
