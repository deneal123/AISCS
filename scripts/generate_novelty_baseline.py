"""Generate the unranked Drosophila x ECAP x SCS novelty baseline artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-23"

AXES = {
    "drosophila_model": [
        "larva", "adult", "ventral_nerve_cord", "brain_and_cord",
        "restricted_nociceptive_circuit", "embodied_simulation",
    ],
    "observation": [
        "spikes", "calcium_activity", "population_dynamics", "kinematics", "protective_behavior"
    ],
    "perturbation": ["thermal", "mechanical", "chemical", "optogenetic", "electrical"],
    "bridge_mechanism": [
        "representation_transfer", "causal_invariants", "system_identification",
        "domain_adaptation", "hybrid_digital_twin",
    ],
    "scs_task": [
        "ecap_forward_model", "artifact_removal", "recruitment_estimation",
        "parameter_selection", "closed_loop_control", "clinical_response_prediction",
    ],
    "validation_level": [
        "drosophila_simulation", "experimental_fly_data", "physical_measurement_model",
        "human_ecap", "clinical_scs_outcome",
    ],
}

SEARCH_STREAMS = [
    ("NS-01", "Drosophila brain-and-cord connectome", "initial_pass_recorded", ["S738"]),
    ("NS-02", "connectome-constrained Drosophila dynamics", "initial_pass_recorded", ["S739", "S740"]),
    ("NS-03", "Drosophila nociception and sensitization circuits", "initial_pass_recorded", ["S066"]),
    ("NS-04", "Drosophila electrical or optogenetic perturbation models", "open", []),
    ("NS-05", "connectome representation transfer across species", "open", []),
    ("NS-06", "synthetic pretraining and domain adaptation for pain", "initial_pass_recorded", ["S149"]),
    ("NS-07", "physical and volume-conductor ECAP models", "open", ["S105"]),
    ("NS-08", "SCS stimulation-artifact removal", "initial_pass_recorded", ["S159"]),
    ("NS-09", "ECAP neural recruitment estimation", "initial_pass_recorded", ["S105", "S162"]),
    ("NS-10", "closed-loop SCS parameter programming", "open", ["S162"]),
    ("NS-11", "SCS clinical-response prediction", "initial_pass_recorded", ["S033"]),
    ("NS-12", "neuromodulation digital twins and system identification", "open", []),
    ("NS-13", "patents joining connectomes, ECAP and SCS", "open", []),
    ("NS-14", "ClinicalTrials linking ECAP telemetry and outcomes", "open", []),
    ("NS-15", "Russian-language prior art and dissertations", "open", []),
    ("NS-16", "citation and author snowballing for direct analogues", "open", []),
]

VARIANT_SPECS = [
    ("NV-001", "Connectome-pretrained ECAP recruitment representation", "representation_transfer", "recruitment_estimation"),
    ("NV-002", "Causal perturbation invariants for ECAP recruitment", "causal_invariants", "recruitment_estimation"),
    ("NV-003", "System identification from fly dynamics to an ECAP forward model", "system_identification", "ecap_forward_model"),
    ("NV-004", "Hybrid connectome and volume-conductor ECAP digital twin", "hybrid_digital_twin", "ecap_forward_model"),
    ("NV-005", "Domain-randomized transfer for patient-specific ECAP calibration", "domain_adaptation", "recruitment_estimation"),
    ("NV-006", "Protective-behavior representation for SCS parameter selection", "representation_transfer", "parameter_selection"),
    ("NV-007", "Connectome-conditioned stimulation-artifact separation", "system_identification", "artifact_removal"),
    ("NV-008", "Causal latent state for adaptive SCS programming", "causal_invariants", "parameter_selection"),
    ("NV-009", "Uncertainty-aware hybrid model for closed-loop SCS", "hybrid_digital_twin", "closed_loop_control"),
    ("NV-010", "Synthetic connectome pretraining for closed-loop control", "representation_transfer", "closed_loop_control"),
    ("NV-011", "Cross-connectome domain adaptation for ECAP robustness", "domain_adaptation", "ecap_forward_model"),
    ("NV-012", "Graph-motif transfer into an ECAP observation operator", "representation_transfer", "ecap_forward_model"),
    ("NV-013", "Multi-fidelity system identification for SCS control", "system_identification", "closed_loop_control"),
    ("NV-014", "Causal connectome constraints for SCS-response modelling", "causal_invariants", "clinical_response_prediction"),
    ("NV-015", "Hybrid Drosophila-to-SCS model for conditional response prediction", "hybrid_digital_twin", "clinical_response_prediction"),
]


def variant(item: tuple[str, str, str, str]) -> dict[str, Any]:
    variant_id, title, mechanism, scs_task = item
    is_clinical = scs_task == "clinical_response_prediction"
    validation = (
        ["drosophila_simulation", "experimental_fly_data", "physical_measurement_model", "human_ecap", "clinical_scs_outcome"]
        if is_clinical
        else ["drosophila_simulation", "experimental_fly_data", "physical_measurement_model", "human_ecap"]
    )
    return {
        "id": variant_id,
        "title": title,
        "problem": (
            "Existing Drosophila connectome models and human SCS/ECAP models are separate; "
            "the transfer object and measurement operator are not jointly formalized."
        ),
        "mechanism": mechanism,
        "bridge": (
            "Drosophila connectome-constrained nociceptive dynamics are encoded as an abstract "
            "state; a separate physical ECAP observation model maps human neural recruitment, "
            f"after which the representation is tested for the SCS task {scs_task}."
        ),
        "expected_new_result": (
            "A reproducible two-model method and falsifiable experiment showing whether the "
            "Drosophila-derived constraint contributes beyond human-only and randomized controls."
        ),
        "axes": {
            "drosophila_model": ["restricted_nociceptive_circuit", "brain_and_cord"],
            "observation": ["spikes", "population_dynamics"],
            "perturbation": ["mechanical", "electrical"],
            "bridge_mechanism": [mechanism],
            "scs_task": [scs_task],
            "validation_level": validation,
        },
        "closest_analogue_refs": ["S149", "S738", "S739", "S105", "S159", "S162"],
        "difference_from_analogues": (
            "The candidate requires both a connectome-constrained Drosophila dynamics model and "
            "a separate physical ECAP operator before an SCS task; the cited analogues cover only "
            "individual parts of this chain."
        ),
        "required_data": [
            "Drosophila connectome and activity/behavior comparator",
            "human ECAP recordings with stimulation geometry",
            *(["patient-linked longitudinal SCS outcome"] if is_clinical else []),
        ],
        "falsification_experiment": (
            "On predefined subject-level splits, compare the complete model with human-only, "
            "random-connectome, shuffled-dynamics, and no-physical-operator controls; reject the "
            "candidate if it gives no prespecified gain or worsens calibration."
        ),
        "permitted_conclusion": (
            "Methodological transfer for the tested ECAP/SCS task only; no claim that Drosophila "
            "experiences human pain or directly models the human spinal cord."
        ),
        "prior_art_outcome": "partial_analogues_only",
        "prior_art_cutoff": DATE,
        "search_trace_ids": ["NS-01", "NS-02", "NS-03", "NS-06", "NS-07", "NS-09", "NS-16"],
        "open_condition": (
            "A final no-direct-analogue statement remains blocked until all open search streams "
            "and citation snowballing are complete."
        ),
    }


def build_search_protocol() -> dict[str, Any]:
    return {
        "meta": {
            "schema_version": "1.0.0",
            "created_at": DATE,
            "cutoff": DATE,
            "status": "first_cycle_open",
        },
        "databases": [
            "PubMed", "Crossref", "OpenAlex", "IEEE Xplore", "arXiv", "bioRxiv",
            "ClinicalTrials.gov", "WIPO Patentscope", "EPO Espacenet", "USPTO",
            "FIPS", "Russian State Library", "eLIBRARY", "official code repositories",
        ],
        "languages": ["en", "ru"],
        "primary_source_policy": (
            "Search engines and aggregators may discover records; technical claims require a "
            "publisher, registry, patent office, dataset owner, or official repository."
        ),
        "search_streams": [
            {
                "id": stream_id,
                "topic": topic,
                "status": status,
                "source_ids": refs,
                "queries_required": ["exact phrase", "synonym expansion", "author search"],
                "snowballing": "backward_and_forward_required",
            }
            for stream_id, topic, status, refs in SEARCH_STREAMS
        ],
        "saturation_rule": (
            "Close only after all streams and backward/forward citation checks are complete and "
            "two consecutive dated query refreshes add neither a direct analogue nor a new mechanism class."
        ),
        "negative_claim_template": (
            "Прямой аналог не найден по документированному протоколу поиска на дату среза."
        ),
    }


def build_landscape() -> dict[str, Any]:
    raw = 1
    for values in AXES.values():
        raw *= len(values)
    return {
        "meta": {
            "schema_version": "1.0.0",
            "created_at": DATE,
            "cutoff": DATE,
            "gate": "G0_REVISE",
            "ranking_policy": "prohibited",
            "status": "unranked_catalogue_first_cycle",
        },
        "morphological_matrix": {
            "axes": AXES,
            "raw_combinations_count": raw,
            "enumeration_policy": (
                "The Cartesian space is represented by equivalence classes after semantic and "
                "physical constraints; no surviving class is ranked."
            ),
            "equivalence_rules": [
                "Stimulus modalities that use the same state-transition and readout mechanism share one class.",
                "Observation variants sharing one latent-state estimator share one class.",
                "Larval and adult implementations remain separate when circuit topology changes the mechanism.",
            ],
            "exclusion_rules": [
                "Exclude any chain that maps a fly signal directly to human ECAP without a physical observation model.",
                "Exclude any chain that treats ECAP as subjective pain.",
                "Exclude clinical-response claims without patient-linked longitudinal outcomes.",
                "Exclude combinations lacking a falsifiable human-only and randomized-control comparison.",
            ],
            "represented_equivalence_classes": len(VARIANT_SPECS),
        },
        "variants": [variant(item) for item in VARIANT_SPECS],
    }


def claim(claim_id: str, text: str, refs: list[str], locators: list[str]) -> dict[str, Any]:
    return {"id": claim_id, "text": text, "source_refs": refs, "locator_refs": locators}


def build_concept() -> dict[str, Any]:
    return {
        "meta": {
            "schema_version": "1.0.0",
            "created_at": DATE,
            "gate": "G0_REVISE",
            "author_review_required": True,
            "supervisor_decision_required": True,
        },
        "title_ru": (
            "Методы коннектомно-ограниченного моделирования нейродинамики Drosophila "
            "и переноса представлений в физически обоснованные модели ECAP для адаптивной "
            "спинальной нейростимуляции"
        ),
        "title_en": (
            "Connectome-constrained modelling of Drosophila neural dynamics and representation "
            "transfer to physically grounded ECAP models for adaptive spinal cord stimulation"
        ),
        "architecture": {
            "id": "ARCH-DROSOPHILA-ECAP-SCS-01",
            "chain": [
                "Drosophila connectome-constrained dynamics",
                "abstract nociceptive-response representation",
                "separate human ECAP physical observation model",
                "SCS programming or evaluation task",
            ],
        },
        "scientific_problem": (
            "There is no validated method for testing whether constraints learned from a compact, "
            "experimentally tractable connectome improve human ECAP/SCS modelling beyond human-only "
            "and randomized synthetic controls."
        ),
        "object": "Neural dynamics and evoked electrophysiological responses under external stimulation.",
        "subject": (
            "Methods for connectome-constrained simulation, representation transfer, and physical "
            "ECAP observation in adaptive SCS tasks."
        ),
        "goal": (
            "Develop and falsifiably evaluate a two-model method in which Drosophila connectome "
            "dynamics constrain a transferable representation and a separate physical operator "
            "maps human neural recruitment to ECAP for an SCS task."
        ),
        "hypothesis": {
            "id": "H-DES-01",
            "text": (
                "A representation pretrained on biologically constrained Drosophila neural dynamics, "
                "when connected to a separately validated ECAP observation model, improves a "
                "predeclared human ECAP/SCS metric over human-only, randomized-connectome, shuffled-"
                "dynamics, and naive-synthetic controls without worsening calibration."
            ),
        },
        "actuality": [
            claim("ACT-01", "Whole adult Drosophila brain-and-cord connectomes now support circuit-scale computational models.", ["S738", "S739", "S740"], ["EV:S738", "EV:S739", "EV:S740"]),
            claim("ACT-02", "Human ECAP provides an objective neural-recruitment signal but is not a direct pain measure.", ["S105", "S162"], ["EV:S105", "EV:S162"]),
            claim("ACT-03", "Synthetic pain domain adaptation already exists, so synthetic pretraining alone cannot constitute novelty.", ["S149"], ["EV:S149"]),
            claim("ACT-04", "Existing SCS-response prediction does not establish a Drosophila-to-ECAP transfer chain.", ["S033", "S105"], ["EV:S033", "EV:S105"]),
        ],
        "tasks": [
            {"id": "TASK-01", "text": "Construct and validate a bounded Drosophila nociceptive-dynamics simulator."},
            {"id": "TASK-02", "text": "Define the transferable state and randomized biological controls."},
            {"id": "TASK-03", "text": "Implement the independent ECAP forward/measurement model."},
            {"id": "TASK-04", "text": "Evaluate transfer on subject-level human ECAP data."},
            {"id": "TASK-05", "text": "Evaluate an SCS programming task and calibration against baselines."},
            {"id": "TASK-06", "text": "Conditionally evaluate clinical response only with linked outcome data."},
        ],
        "novelty_claims": [
            claim("NOV-01", "Candidate method: a two-model Drosophila-dynamics and human-ECAP bridge with an explicit physical observation operator.", ["S738", "S739", "S105"], ["NS-01", "NS-02", "NS-07"]),
            claim("NOV-02", "Candidate experiment: isolate biological contribution using random-connectome, shuffled-dynamics, naive-synthetic, and human-only controls.", ["S149", "S739"], ["NS-02", "NS-06"]),
            claim("NOV-03", "Candidate system result: uncertainty-aware SCS parameter estimation that abstains outside the validated ECAP domain.", ["S105", "S159", "S162"], ["NS-08", "NS-09", "NS-10"]),
        ],
        "defense_propositions": [
            claim("DEF-01", "The Drosophila simulator reproduces predefined neural and behavioral nociceptive-response observables.", ["S066", "S738", "S740"], ["EV:S066", "EV:S738", "EV:S740"]),
            claim("DEF-02", "The physical ECAP operator reproduces predefined waveform and recruitment characteristics independently of the fly model.", ["S105", "S159", "S162"], ["EV:S105", "EV:S159", "EV:S162"]),
            claim("DEF-03", "The complete transfer method is assessed only by prospective baselines and subject-level held-out data.", ["S149", "S105"], ["EV:S149", "EV:S105"]),
        ],
        "falsification": [
            "Reject the simulator claim if it fails predefined fly activity or behavior observables.",
            "Reject the ECAP-like claim if waveform/latency/recruitment tolerances fail on human ECAP.",
            "Reject the transfer hypothesis if the primary metric does not improve or calibration worsens.",
            "Do not make a clinical-response claim without linked longitudinal SCS outcomes.",
        ],
        "forbidden_claims": [
            "Drosophila simulation represents subjective human pain.",
            "The fly nervous system is a direct digital twin of the human spinal cord.",
            "ECAP is a direct measure of pain.",
            "Simulation-only results prove clinical SCS effectiveness.",
        ],
        "specialty_alignment": {
            "specialty": "2.2.12 Приборы, системы и изделия медицинского назначения",
            "status": "passport_text_review_required",
            "boundary": (
                "The defensible contribution must be a medical-instrumentation modelling, "
                "measurement, or control method, not merely software implementation."
            ),
        },
    }


def main() -> int:
    outputs = {
        "search-protocol.json": build_search_protocol(),
        "novelty-landscape.json": build_landscape(),
        "dissertation-concept.json": build_concept(),
    }
    for name, payload in outputs.items():
        atomic_write_json(DATA / name, payload)
    print(json.dumps({"ok": True, "files": sorted(outputs)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
