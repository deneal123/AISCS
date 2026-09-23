"""Populate the seventh relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-007.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S318": alias(
            "S318",
            "S228",
            "Cloud-Powered Federated Learning for Healthcare",
            "https://www.dsu.edu.in/images/Engineering/CSE-dept/Newsletter/CsOct-Dec_2025.pdf",
        ),
        "S319": alias(
            "S319",
            "S286",
            "Whole-Brain Connectomic GNN (final)",
            "https://arxiv.org/abs/2602.17997",
        ),
        "S329": alias(
            "S329",
            "S187",
            "FANN: Federated Adaptive Neuromodulation (extended)",
            "https://unpatentable.org/innovation/federated-adaptive-neuromodulation-network-fann-for-community-based-mental-health-treatment/",
        ),
        "S332": alias("S332", "S286", "flyGNN (final)", "https://arxiv.org/abs/2602.17997"),
        "S333": alias(
            "S333",
            "S282",
            "Descending neurons (final)",
            "https://www.biorxiv.org/content/10.1101/2025.09.30.679458v1",
        ),
        "S344": alias(
            "S344",
            "S187",
            "FANN (final)",
            "https://unpatentable.org/innovation/federated-adaptive-neuromodulation-network-fann-for-community-based-mental-health-treatment/",
        ),
        "S346": alias(
            "S346",
            "S013",
            "Beyond Reflex (Dissertation, final)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S071": canonical(
            "S071",
            "verified_metadata",
            "Assessing Pain from Neurophysiological Signals: Machine Learning Approaches Using Functional Connectivity",
            "https://repository.essex.ac.uk/38532/",
            authors="Yiyuan Han",
            source="University of Essex doctoral thesis",
            note="The institutional record and thesis PDF are available, and the abstract describes EEG functional-connectivity and transfer-learning analyses. Detailed cohorts, participant splits, metrics and external validation were not independently extracted.",
            target="experimental_pain_class",
            role="human_validation",
            risks=["metadata_only", "missing_cross_subject_validation"],
            claim="The doctoral thesis studies EEG functional-connectivity biomarkers and CNN-based transfer learning for pain assessment.",
        ),
        "S173": alias(
            "S173",
            "S071",
            "Assessing Pain from Neurophysiological Signals: ML Approaches (extended)",
            "https://repository.essex.ac.uk/38532/",
        ),
        "S229": canonical(
            "S229",
            "verified_metadata",
            "EPOC: A 28-nm 5.3 pJ/SOP Event-Driven Parallel Neuromorphic Hardware With Neuromodulation-Based Online Learning",
            "https://pubmed.ncbi.nlm.nih.gov/39356594/",
            doi="10.1109/TBCAS.2024.3470520",
            authors="Faquan Chen; Qingyang Tian; Lisheng Xie; Yifan Zhou; Ziren Wu; Liangshun Wu; Rendong Ying; Fei Wen; Peilin Liu",
            source="IEEE Transactions on Biomedical Circuits and Systems",
            note="Bibliographic metadata and abstract-level hardware claims are confirmed. Here neuromodulation denotes a learning mechanism in neuromorphic hardware, not therapeutic neuromodulation, SCS, ECAP or pain assessment.",
            target="not_applicable",
            role="context_only",
            risks=["metadata_only"],
            claim="EPOC implements an event-driven neuromorphic processor with a unified neuromodulation-based online-learning framework.",
        ),
        "S268": alias(
            "S268",
            "S229",
            "EPOC: Neuromorphic Hardware (extended)",
            "https://doi.org/10.1109/TBCAS.2024.3470520",
        ),
        "S328": alias(
            "S328",
            "S229",
            "EPOC: Neuromorphic Hardware (final)",
            "https://doi.org/10.1109/TBCAS.2024.3470520",
        ),
        "S343": alias(
            "S343",
            "S229",
            "EPOC: Neuromorphic Hardware (final extended)",
            "https://doi.org/10.1109/TBCAS.2024.3470520",
        ),
        "S012": canonical(
            "S012",
            "verified_primary",
            "Drosophila as a Model to Study the Mechanism of Nociception",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC8996152/",
            doi="10.3389/fphys.2022.854124",
            authors="Jianzheng He; Botong Li; Shuzhen Han; Yuan Zhang; Kai Liu; Simeng Yi; Yongqi Liu; Minghui Xiu",
            source="Frontiers in Physiology",
            note="The review explicitly distinguishes subjective pain from objective nociception and surveys fly genetics, sensory neurons and behavioral assays. Conservation does not establish equivalence to human pain or a spinal-cord model.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The review summarizes conserved Drosophila nociception mechanisms and thermal, chemical and mechanical behavioral assays.",
        ),
        "S222": canonical(
            "S222",
            "verified_primary",
            "A brain-inspired robot pain model based on a spiking neural network",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC9807619/",
            doi="10.3389/fnbot.2022.1025338",
            authors="Hui Feng; Yi Zeng",
            source="Frontiers in Neurorobotics",
            note="The engineered internal variable called robot pain drives self-protective tasks. It is a conceptual robotic construct and cannot be treated as evidence of subjective pain, biological nociception or clinical transfer.",
            target="protective_behavior",
            role="method_baseline",
            risks=["synthetic_only", "claim_not_supported"],
            claim="BRP-SNN couples multimodal damage cues to an engineered internal state and tests alerting and avoidance tasks on robots.",
        ),
        "S267": alias(
            "S267",
            "S222",
            "Brain-inspired robot pain SNN (extended)",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC9807619/",
        ),
        "S306": alias(
            "S306",
            "S222",
            "BRP-SNN: Brain-inspired robot pain SNN (extended)",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC9807619/",
        ),
    }
    decisions["S229"]["updates"]["identifiers"]["pmid"] = "39356594"
    decisions["S012"]["updates"]["identifiers"]["pmid"] = "35418874"
    decisions["S222"]["updates"]["identifiers"]["pmid"] = "36605522"
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
