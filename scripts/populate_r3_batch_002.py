"""Populate the second relevance-3 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-3" / "batches" / "r3-batch-002.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S250": rejected(
            "S250",
            "Brain Sovereignty Demands Privacy-Enhancing AI by Default",
            "https://inferensys.com/blog/neurotechnology-and-precision-neurology/why-brain-sovereignty-requires-privacy-enhancing-ai-by-default",
            "The exact match is a commercial blog post with unsupported legal, performance and market claims, not a scholarly or authoritative regulatory source.",
        ),
        "S314": alias(
            "S314",
            "S250",
            "Brain Sovereignty Demands Privacy-Enhancing AI",
            "https://inferensys.com/blog/neurotechnology-and-precision-neurology/why-brain-sovereignty-requires-privacy-enhancing-ai-by-default",
        ),
        "S061": canonical(
            "S061",
            "verified_primary",
            "Synaptic density and relative connectivity conservation maintain circuit stability across development",
            "https://elifesciences.org/reviewed-preprints/108643",
            doi="10.7554/eLife.108643.1",
            authors="Ingo Fritz; Feiyu Wang; Ricardo Chirif; Nikos Malakasis; Julijana Gjorgjieva; Andre Ferreira Castro",
            source="eLife reviewed preprint",
            note="The study combines EM reconstructions and passive single-cell modeling of a larval nociceptive circuit across development. It does not model whole-brain dynamics, subjective pain or human transfer.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["preprint", "animal_to_human_transfer_unvalidated"],
            claim="Conserved synaptic density and relative connectivity can maintain modeled postsynaptic responses as the larval nociceptive circuit grows.",
        ),
        "S062": canonical(
            "S062",
            "verified_primary",
            "Ascending nociceptive pathways drive rapid escape and sustained avoidance in adult Drosophila",
            "https://pubmed.ncbi.nlm.nih.gov/41280033/",
            doi="10.1101/2025.10.28.684868",
            authors="Jessica M Jones; Anne Sustar; Akira Mamiya; Sarah Walling-Bell; Grant M Chou; Andrew P Cook; John C Tuthill",
            source="bioRxiv",
            note="The preprint identifies adult-fly nociceptors and ascending pathways supporting escape and sustained avoidance. Its discussion of pain criteria does not demonstrate subjective experience or human transfer.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["preprint", "animal_to_human_transfer_unvalidated"],
            claim="Adult abdominal multidendritic neurons and distinct ascending pathways support rapid escape and sustained avoidance of noxious heat.",
        ),
        "S169": alias(
            "S169",
            "S062",
            "Shifts in sensory tuning from larva to adult (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/41280033/",
        ),
        "S095": canonical(
            "S095",
            "partially_verified",
            "From Connectome to Cognition: Building the First Digital Organism",
            "https://doi.org/10.59973/ipil.361",
            doi="10.59973/ipil.361",
            authors="Melvin M Vopson",
            source="IPI Letters, News and Views",
            note="The article is a News and Views interpretation of prior connectome and Eon work. Its 'first digital organism' framing is commentary, not independent empirical validation of a complete brain emulation or cognition.",
            target="not_applicable",
            role="context_only",
            risks=["news_or_secondary_source", "claim_not_supported"],
            claim="The commentary links the adult fly connectome, computational brain model and later embodied demonstrations into a digital-organism narrative.",
        ),
        "S154": canonical(
            "S154",
            "verified_primary",
            "RNA Sequencing Dataset of Drosophila Nociceptor Translatomic Response to Injury",
            "https://pubmed.ncbi.nlm.nih.gov/40855845/",
            doi="10.3390/data10020011",
            authors="Christine M Hale; Kyle J Beauchemin; Courtney L Brann; Julie K Moulton; Ramaz Geguchadze; Benjamin J Harrison; Geoffrey K Ganter",
            source="Data",
            note="The dataset compares nociceptor-specific ribosome-bound RNA after UV injury versus sham in larvae. It is molecular translatomic data, not neural activity, behavior, subjective pain or human validation.",
            target="nociceptive_response",
            role="dataset_descriptor",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The data descriptor provides injury and sham larval nociceptor translatomes under BioProject PRJNA1056042.",
        ),
        "S168": alias(
            "S168",
            "S061",
            "Drosophila larval connectome: synaptic density (extended)",
            "https://elifesciences.org/reviewed-preprints/108643",
        ),
        "S247": canonical(
            "S247",
            "verified_primary",
            "A Neuromodulable Current-Mode Silicon Neuron for Robust and Adaptive Neuromorphic Systems",
            "https://arxiv.org/abs/2512.01133",
            authors="Loris Mendolia; Chenxi Wen; Elisabetta Chicca; Giacomo Indiveri; Rodolphe Sepulchre; Jean-Michel Redoute; Alessio Franci",
            source="arXiv",
            note="The preprint validates an analog CMOS neuron circuit. 'Neuromodulable' describes electronic adaptation; it is not therapeutic neuromodulation, nociception, pain assessment, ECAP or SCS evidence.",
            target="technical_signal_quality",
            role="context_only",
            risks=["preprint"],
            claim="A 180 nm CMOS implementation demonstrates tunable firing regimes and robustness of a mixed-feedback current-mode silicon neuron.",
        ),
        "S152": canonical(
            "S152",
            "verified_primary",
            "Nociception in fruit fly larvae",
            "https://pubmed.ncbi.nlm.nih.gov/37006412/",
            doi="10.3389/fpain.2023.1076017",
            authors="Jean-Christophe Boivin; Jiayi Zhu; Tomoko Ohyama",
            source="Frontiers in Pain Research",
            note="The review covers larval nociceptive circuits, connectomics, behavior and neuromodulation. Cross-species relevance is hypothesis-generating and does not establish subjective pain or a human spinal mapping.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The review summarizes known larval nociceptors, downstream circuits, nocifensive behaviors and neuromodulators.",
        ),
        "S214": canonical(
            "S214",
            "verified_primary",
            "A lightweight data-driven spiking neuronal network model of Drosophila olfactory nervous system with dedicated hardware support",
            "https://pubmed.ncbi.nlm.nih.gov/38994271/",
            doi="10.3389/fnins.2024.1384336",
            authors="Takuya Nanami; Daichi Yamada; Makoto Someya; Toshihide Hige; Hokto Kazama; Takashi Kohno",
            source="Frontiers in Neuroscience",
            note="The model targets olfaction and associative learning and runs on FPGA hardware. It does not model nociception, whole-brain dynamics, pain or human transfer.",
            target="not_applicable",
            role="simulation_foundation",
            risks=["synthetic_only", "animal_to_human_transfer_unvalidated"],
            claim="The paper builds a connectome-informed lightweight SNN of the Drosophila olfactory system and demonstrates real-time FPGA execution.",
        ),
        "S266": alias(
            "S266",
            "S214",
            "A lightweight data-driven SNN model (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/38994271/",
        ),
        "S307": alias(
            "S307",
            "S214",
            "A lightweight data-driven SNN model (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/38994271/",
        ),
        "S157": alias(
            "S157",
            "S012",
            "Drosophila as a Model to Study Nociception",
            "https://pubmed.ncbi.nlm.nih.gov/35418874/",
        ),
    }
    decisions["S062"]["updates"]["identifiers"]["pmid"] = "41280033"
    decisions["S154"]["updates"]["identifiers"]["pmid"] = "40855845"
    decisions["S154"]["updates"]["identifiers"]["dataset_id"] = "PRJNA1056042"
    decisions["S247"]["updates"]["identifiers"]["arxiv_id"] = "2512.01133"
    decisions["S152"]["updates"]["identifiers"]["pmid"] = "37006412"
    decisions["S214"]["updates"]["identifiers"]["pmid"] = "38994271"
    decisions["S214"]["updates"]["год"] = 2024
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
