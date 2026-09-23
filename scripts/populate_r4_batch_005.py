"""Populate the fifth relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-005.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S102": alias(
            "S102",
            "S075",
            "Deep learning and noninvasive sensors for physiological dysregulation",
            "https://pubmed.ncbi.nlm.nih.gov/41615529/",
        ),
        "S121": alias(
            "S121",
            "S200",
            "Fly brain simulation with aversive feedback (DoomFly)",
            "https://github.com/nftechie/doomfly",
        ),
        "S122": rejected(
            "S122",
            "Ethics of whole-brain connectome simulations",
            "https://scholar.google.com/scholar?q=%22Ethics+of+whole-brain+connectome+simulations%22",
            "No uniquely identifiable scholarly source with this exact generic title was found.",
        ),
        "S136": alias(
            "S136",
            "S200",
            "DoomFly: Fly brain plays Doom with pain feedback",
            "https://github.com/nftechie/doomfly",
        ),
        "S354": alias(
            "S354",
            "S200",
            "DOOMFLY: Fly brain plays Doom with pain feedback",
            "https://github.com/nftechie/doomfly",
        ),
        "S211": alias(
            "S211",
            "S013",
            "Beyond Reflex: Nociception, Neural Circuits, and Memory (Dissertation)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S233": rejected(
            "S233",
            "The Mousing Problem: Whole-Brain Emulation Makes AI Suffering Measurable",
            "https://scholar.google.com/scholar?q=%22The+Mousing+Problem%22+%22Whole-Brain+Emulation%22",
            "No primary scholarly publication or stable repository record was found; later web commentary is insufficient evidence.",
        ),
        "S235": alias(
            "S235",
            "S368",
            "Google open-sources fly brain connectome (DoomFly coverage)",
            "https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/",
        ),
        "S249": canonical(
            "S249",
            "verified_primary",
            "Decision-Centered Wearable Biosensors for Personalized Rehabilitation: Integrating Multimodal Monitoring, Artificial Intelligence, and Closed-Loop Intervention",
            "https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2026.1948186/full",
            doi="10.3389/fbioe.2026.1948186",
            authors="Fujin Jia; Xinzhu Li; Hui Song; Xinyue Liu; Yuli Tang; Qingping Wen; Ping Wu",
            source="Frontiers in Bioengineering and Biotechnology",
            note="Critical narrative review, not a trial. It emphasizes uncertainty, safe degradation, clinician oversight and patient-important outcomes as prerequisites for closed-loop rehabilitation systems.",
            target="clinical_function",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The review proposes a decision-centered framework for evaluating wearable biosensor systems in personalized rehabilitation.",
        ),
        "S253": canonical(
            "S253",
            "partially_verified",
            "How the Eon Team Produced a Virtual Embodied Fly",
            "https://eon.systems/updates/embodied-brain-emulation",
            authors="Scott Harris; Aarav Sinha; Viktor Toth; Alexis Pomares; Philip Shiu",
            source="Eon Systems technical update",
            note="The company technical post documents integration of published components and explicitly lists major simplifications. It is non-peer-reviewed, work in progress, and does not independently validate behavioral fidelity, nociception or affect.",
            target="protective_behavior",
            role="simulation_foundation",
            risks=[
                "news_or_secondary_source",
                "synthetic_only",
                "animal_to_human_transfer_unvalidated",
            ],
            claim="Eon documents a closed sensorimotor integration of a connectome-constrained fly model with NeuroMechFly and MuJoCo for a small behavior subset.",
        ),
        "S254": alias(
            "S254",
            "S253",
            "Virtual embodied fly with physical simulation",
            "https://eon.systems/updates/embodied-brain-emulation",
        ),
        "S287": alias(
            "S287",
            "S253",
            "Eon Systems: Embodied whole-brain emulation",
            "https://eon.systems/updates/embodied-brain-emulation",
        ),
        "S288": alias(
            "S288",
            "S320",
            "Emergent Individuality in Whole-Brain Connectome Simulations",
            "https://doi.org/10.5281/zenodo.19152238",
        ),
        "S292": rejected(
            "S292",
            "Embodied Whole-Brain Spiking Simulation of Drosophila (claude-fly)",
            "https://github.com/search?q=%22claude-fly%22+%22whole-brain%22&type=repositories",
            "No stable repository or publication matching the supplied claude-fly title was identified.",
        ),
        "S312": alias(
            "S312",
            "S249",
            "Decision-centered wearable biosensors",
            "https://doi.org/10.3389/fbioe.2026.1948186",
        ),
        "S315": alias(
            "S315",
            "S330",
            "Towards Personalized Edge-AI for Medicine",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        ),
        "S010": alias(
            "S010",
            "S212",
            "Combining brain-wide activity imaging with electron microscopy reveals a distributed nociceptive network in the brain",
            "https://doi.org/10.1101/2025.09.25.678485",
        ),
        "S025": canonical(
            "S025",
            "verified_primary",
            "A predictive corticospinal model for pain perception",
            "https://doi.org/10.1016/j.xcrm.2026.102793",
            doi="10.1016/j.xcrm.2026.102793",
            source="Cell Reports Medicine",
            note="The primary article reports independent-dataset tests across experimental pain, TENS and chronic pain. It is an fMRI biomarker study, not ECAP evidence or an SCS-response model; full authorship metadata remains to be completed.",
            target="self_reported_pain",
            role="human_validation",
            risks=["missing_authors"],
            claim="The corticospinal fMRI model is evaluated across experimental and chronic-pain datasets and tracks TENS-associated changes.",
        ),
        "S032": alias(
            "S032",
            "S212",
            "Combining brain-wide activity imaging with electron microscopy reveals a distributed nociceptive network",
            "https://doi.org/10.1101/2025.09.25.678485",
        ),
        "S042": canonical(
            "S042",
            "verified_primary",
            "Preserving privacy in big data research: the role of federated learning in spine surgery",
            "https://doi.org/10.1007/s00586-024-08172-2",
            doi="10.1007/s00586-024-08172-2",
            authors="Hania Shahzad; Cole Veliky; Hai Le; Sheeraz Qureshi; Frank M Phillips; Yashar Javidan; Safdar N Khan",
            source="European Spine Journal",
            note="Narrative review of federated learning opportunities in spine surgery; it is not a deployed federated SCS model or outcome-validation study.",
            target="not_applicable",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The review describes privacy and data-sharing motivations for federated learning in spine-surgery research.",
        ),
        "S051": alias(
            "S051",
            "S042",
            "Preserving privacy in big data research: FL in spine surgery",
            "https://doi.org/10.1007/s00586-024-08172-2",
        ),
        "S043": alias(
            "S043",
            "S212",
            "Advanced brain-wide imaging + EM reveals novel nociceptive circuits",
            "https://doi.org/10.1101/2025.09.25.678485",
        ),
        "S083": canonical(
            "S083",
            "verified_primary",
            "Synthetic Thermal and RGB Videos for Automatic Pain Assessment Utilizing a Vision-MLP Architecture",
            "https://arxiv.org/abs/2407.19811",
            doi="10.1109/ACIIW63320.2024.00006",
            authors="Stefanos Gkikas; Manolis Tsiknakis",
            source="ACIIW 2024 / arXiv",
            note="The method generates synthetic thermal video from BioVid facial video and evaluates benchmark recognition. It does not create physiological ground truth or demonstrate clinical transfer.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["synthetic_only", "missing_cross_subject_validation"],
            claim="The conference paper evaluates GAN-derived thermal videos with RGB video for automatic pain assessment on BioVid.",
        ),
        "S155": alias(
            "S155",
            "S013",
            "Beyond Reflex: Nociception, Neural Circuits, and Memory",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
    }
    decisions["S025"]["updates"]["год"] = 2026
    decisions["S042"]["updates"]["identifiers"]["pmid"] = "38403832"
    decisions["S042"]["updates"]["год"] = 2024
    decisions["S083"]["updates"]["identifiers"]["arxiv_id"] = "2407.19811"
    decisions["S083"]["updates"]["год"] = 2024
    missing = set(payload["source_ids"]) - decisions.keys()
    extra = decisions.keys() - set(payload["source_ids"])
    if missing or extra:
        raise RuntimeError({"missing": sorted(missing), "extra": sorted(extra)})
    payload["decisions"] = [decisions[source_id] for source_id in payload["source_ids"]]
    payload["meta"].update({"status": "reviewed", "reviewed_at": TODAY})
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
