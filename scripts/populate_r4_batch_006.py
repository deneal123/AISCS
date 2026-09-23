"""Populate the sixth relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-006.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S165": canonical(
            "S165",
            "verified_primary",
            "Artificial Intelligence-Driven Neuromodulation in Neurodegenerative Disease: Precision in Chaos, Learning in Loss",
            "https://pubmed.ncbi.nlm.nih.gov/41007681/",
            doi="10.3390/biomedicines13092118",
            authors="Andrea Calderone; Desiree Latella; Elvira La Fauci; Roberta Puleo; Arturo Sergi; Mariachiara De Francesco; Maria Mauro; Angela Foti; Leda Salemi; Rocco Salvatore Calabro",
            source="Biomedicines",
            note="Narrative review of AI-enabled neuromodulation in neurodegenerative rehabilitation. It is not an SCS trial, a pain study, or evidence for federated SCS-response prediction.",
            target="not_applicable",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The narrative review maps AI-supported adaptive neuromodulation approaches and their translational constraints in neurodegenerative rehabilitation.",
        ),
        "S186": alias(
            "S186",
            "S165",
            "AI-Driven Neuromodulation in Neurodegenerative Disease",
            "https://pubmed.ncbi.nlm.nih.gov/41007681/",
        ),
        "S187": rejected(
            "S187",
            "Federated Adaptive Neuromodulation Network (FANN)",
            "https://unpatentable.org/innovation/federated-adaptive-neuromodulation-network-fann-for-community-based-mental-health-treatment/",
            "The exact item is an idea-platform concept, not a scholarly publication, registered trial, patent, dataset, or validated neuromodulation system.",
        ),
        "S309": alias(
            "S309",
            "S187",
            "Federated Adaptive Neuromodulation Network (FANN)",
            "https://unpatentable.org/innovation/federated-adaptive-neuromodulation-network-fann-for-community-based-mental-health-treatment/",
        ),
        "S188": alias(
            "S188",
            "S330",
            "Neuromorphic Neuromodulation: Low-Power Edge-Training",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        ),
        "S230": alias(
            "S230",
            "S330",
            "Neuromorphic Neuromodulation: Low-Power Edge-Training (extended)",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        ),
        "S192": canonical(
            "S192",
            "verified_primary",
            "PainDiffusion: Learning to Express Pain",
            "https://arxiv.org/abs/2409.11635",
            doi="10.1109/IROS60139.2025.11247588",
            authors="Quang Tien Dam; Tri Tung Nguyen Nguyen; Yuuki Endo; Dinh Tuan Tran; Joo-Ho Lee",
            source="IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS 2025) / arXiv",
            note="The model synthesizes facial expressions for robotic-patient simulation from pain-stimulus controls. It is not a pain detector, physiological simulator, or clinical validation source.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["synthetic_only", "missing_cross_subject_validation"],
            claim="PainDiffusion generates controllable facial pain expressions for virtual or robotic patient simulation and reports conference benchmark evaluation.",
        ),
        "S223": alias(
            "S223",
            "S192",
            "PainDiffusion: Learning to Express Pain",
            "https://arxiv.org/abs/2409.11635",
        ),
        "S228": canonical(
            "S228",
            "verified_metadata",
            "Cloud-Powered Federated Learning for Global Healthcare Diagnostics: Privacy Preserving Multi-Cloud Architecture",
            "https://www.dsu.edu.in/images/Engineering/CSE-dept/Newsletter/CsOct-Dec_2025.pdf",
            authors="Bharath M B; Mala B A; M Kiruthika; Pooja Shree H R; Sharanabasappa Tadkal",
            source="7th International Conference on Information Management & Machine Intelligence (ICIMMI 2025)",
            note="The conference presentation and bibliographic identity are corroborated, but no DOI or primary full text was located and its claims were not checked. It is generic healthcare infrastructure, not SCS evidence.",
            target="not_applicable",
            role="context_only",
            risks=["metadata_only", "missing_cross_subject_validation"],
            claim="Conference metadata identifies a privacy-preserving multi-cloud federated-learning architecture for healthcare diagnostics.",
        ),
        "S244": canonical(
            "S244",
            "verified_primary",
            "A Wearable EMG-Driven Closed-Loop TENS Platform for Real-Time, Personalized Pain Modulation",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12390560/",
            doi="10.3390/s25165113",
            authors="Jiahao Du; Shengli Luo; Ping Shi",
            source="Sensors",
            note="The paper validates hardware and EMG-trigger timing mainly on bench and synthetic input. Human analgesic testing remained a prospective protocol, so it cannot support efficacy claims.",
            target="technical_signal_quality",
            role="method_baseline",
            risks=["claim_not_supported", "missing_cross_subject_validation"],
            claim="The wearable six-channel TENS prototype demonstrates EMG-triggered closed-loop operation and bench-level timing and waveform performance.",
        ),
        "S255": alias(
            "S255", "S192", "PainDiffusion (extended)", "https://arxiv.org/abs/2409.11635"
        ),
        "S303": alias(
            "S303", "S192", "PainDiffusion (extended)", "https://arxiv.org/abs/2409.11635"
        ),
        "S381": alias("S381", "S192", "PainDiffusion (final)", "https://arxiv.org/abs/2409.11635"),
        "S269": alias(
            "S269",
            "S330",
            "Neuromorphic Neuromodulation (final)",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        ),
        "S274": alias(
            "S274",
            "S244",
            "A Wearable EMG-Driven CL-TENS Platform (extended)",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12390560/",
        ),
        "S281": alias(
            "S281",
            "S013",
            "Beyond Reflex: Nociception, Neural Circuits, Memory (Dissertation)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S282": canonical(
            "S282",
            "verified_primary",
            "Descending neurons integrate learnt information from mushroom body with context to promote escape behaviour",
            "https://www.biorxiv.org/content/10.1101/2025.09.30.679458v1",
            doi="10.1101/2025.09.30.679458",
            authors="Benjamin M W Jones; Samuel N Harris; Nicolo G Ceffa; Albert Cardona; Marta Zlatic",
            source="bioRxiv",
            note="Larval Drosophila connectomics, imaging, neural manipulation and behavior identify a circuit for context-dependent rolling. This is nociceptive escape circuitry, not subjective pain or human transfer.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["preprint", "animal_to_human_transfer_unvalidated"],
            claim="The preprint identifies descending neurons that integrate learned mushroom-body information with nociceptive context to promote larval escape rolling.",
        ),
        "S286": canonical(
            "S286",
            "verified_primary",
            "Whole-Brain Connectomic Graph Model Enables Whole-Body Locomotion Control in Fruit Fly",
            "https://arxiv.org/abs/2602.17997",
            authors="Zehao Jin; Yaoye Zhu; Chen Zhang; Yanan Sui",
            source="arXiv",
            note="FlyGM uses the adult connectome as a graph-structured controller in a simulated biomechanical fly. It validates an embodied-control architecture, not biophysical neural dynamics, nociception, pain, or human transfer.",
            target="protective_behavior",
            role="simulation_foundation",
            risks=["preprint", "synthetic_only", "animal_to_human_transfer_unvalidated"],
            claim="FlyGM embeds the adult Drosophila connectome into a graph policy and evaluates locomotion control in a biomechanical simulation.",
        ),
        "S293": alias(
            "S293",
            "S286",
            "flyGNN: Whole-Brain Connectomic GNN (extended)",
            "https://arxiv.org/abs/2602.17997",
        ),
        "S294": alias(
            "S294",
            "S282",
            "Descending neurons integrate learnt information (extended)",
            "https://www.biorxiv.org/content/10.1101/2025.09.30.679458v1",
        ),
        "S295": alias(
            "S295",
            "S013",
            "Beyond Reflex (extended)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S334": alias(
            "S334",
            "S013",
            "Beyond Reflex (final)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S396": alias(
            "S396",
            "S013",
            "Beyond Reflex (final extended)",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
        ),
        "S310": rejected(
            "S310",
            "Privacy-Preserving Latent Manifold Adaptation",
            "https://scholar.google.com/scholar?q=%22Privacy-Preserving+Latent+Manifold+Adaptation%22",
            "Only an unstable ResearchGate upload with anomalous citation metadata was found; no publisher, DOI, repository, proceedings record, or other primary bibliographic record could be verified.",
        ),
        "S311": rejected(
            "S311",
            "Data Flow+: Edge Computing and Local Intelligence",
            "https://scholar.google.com/scholar?q=%22Data+Flow%2B%22+%22Edge+Computing+and+Local+Intelligence%22",
            "No exact scholarly source, stable repository record, patent, dataset, or software project matching this title was found.",
        ),
    }
    decisions["S165"]["updates"]["identifiers"]["pmid"] = "41007681"
    decisions["S192"]["updates"]["identifiers"]["arxiv_id"] = "2409.11635"
    decisions["S244"]["updates"]["identifiers"]["pmid"] = "40871975"
    decisions["S286"]["updates"]["identifiers"]["arxiv_id"] = "2602.17997"
    decisions["S286"]["updates"]["год"] = 2026
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
