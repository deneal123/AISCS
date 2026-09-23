"""Populate the fourth relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-004.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S074": canonical(
            "S074",
            "verified_metadata",
            "Multimodal Fusion of Physiological and Psychosocial Parameters for Intelligent Pain Intensity Assessment in Sickle Cell Disease Using Ensemble Learning and LSTM Framework",
            "https://www.proceedings.com/content/082/082935webtoc.pdf",
            authors="Chanchal Dahat; Goldi Soni",
            source="ICICNCT 2025 proceedings table of contents",
            note="The exact conference paper and authors are confirmed in the proceedings contents, but the paper text, cohort, split and metrics were not verified.",
            target="self_reported_pain",
            role="method_baseline",
            risks=["metadata_only", "missing_cross_subject_validation"],
            claim="The conference proceedings contain a paper on physiological and psychosocial fusion for sickle-cell pain intensity assessment.",
        ),
        "S116": alias(
            "S116",
            "S074",
            "Multimodal Fusion of Physiological and Psychosocial Parameters",
            "https://www.proceedings.com/content/082/082935webtoc.pdf",
        ),
        "S176": alias(
            "S176",
            "S074",
            "Multimodal Fusion of Physiological and Psychosocial Parameters (extended)",
            "https://www.proceedings.com/content/082/082935webtoc.pdf",
        ),
        "S090": canonical(
            "S090",
            "verified_primary",
            "Optogenetic Stimulation of Nociceptive Escape Behaviors in Drosophila Larvae",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC11787400/",
            doi="10.1101/pdb.prot108128",
            authors="Stephanie E Mauthner; W Daniel Tracey",
            source="Cold Spring Harbor Protocols",
            note="This is an experimental protocol for activating larval nociceptors and eliciting rolling. It validates a nociceptive-behavior assay, not subjective pain or human transfer.",
            target="protective_behavior",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The protocol details optogenetic activation of class-IV multidendritic neurons to elicit nociceptive rolling in Drosophila larvae.",
        ),
        "S133": alias(
            "S133",
            "S090",
            "Optogenetic stimulation of nociceptors (extended)",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC11787400/",
        ),
        "S175": alias(
            "S175",
            "S073",
            "Enhanced deep learning framework for real-time pain (extended)",
            "https://dl.acm.org/action/doSearch?AllField=%22Enhanced+deep+learning+framework+for+real-time+pain+assessment%22",
        ),
        "S189": canonical(
            "S189",
            "verified_primary",
            "Electroencephalography-Based Pain Detection Using Kernel Spectral Connectivity Network with Preserved Spatio-Frequency Interpretability",
            "https://www.mdpi.com/2076-3417/15/9/4804",
            doi="10.3390/app15094804",
            authors="Santiago Buitrago-Osorio; Julian Gil-Gonzalez; Andres Marino Alvarez-Meza; David Cardenas-Pena; Alvaro Orozco-Gutierrez",
            source="Applied Sciences",
            note="The paper evaluates controlled no-pain versus high-pain EEG and includes LOSO analysis, but the reported headline metrics include subject-dependent results and are not clinical-pain validation.",
            target="experimental_pain_class",
            role="human_validation",
            risks=[],
            claim="KCS-FCnet is evaluated on the Brain Mediators of Pain dataset with subject-dependent and leave-one-subject-out analyses.",
        ),
        "S190": canonical(
            "S190",
            "verified_primary",
            "Efficient Pain Recognition via Respiration Signals: A Single Cross-Attention Transformer Multi-Window Fusion Pipeline",
            "https://arxiv.org/abs/2507.21886",
            doi="10.1145/3747327.3764782",
            authors="Stefanos Gkikas; Ioannis Kyprakis; Manolis Tsiknakis",
            source="ICMI 2025 Companion / arXiv",
            note="AI4PAIN challenge method using respiration signals. Benchmark evidence does not establish clinical generalization or an independent external cohort.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["missing_cross_subject_validation"],
            claim="The conference paper evaluates a compact cross-attention, multi-window respiration pipeline for automatic pain recognition.",
        ),
        "S193": canonical(
            "S193",
            "verified_metadata",
            "A Multi-Modal Multi-Expert Framework for Pain Assessment in Postoperative Children",
            "https://doi.org/10.1109/TAFFC.2025.3567307",
            doi="10.1109/TAFFC.2025.3567307",
            authors="Zequan Liang; Hao Luo; Xi Chen; Zhipeng Zhong; Cheng Fan; Xingrong Song; Bilian Li; Jianming Lv",
            source="IEEE Transactions on Affective Computing",
            note="Bibliographic identity and abstract-level claims are confirmed; the full paper, patient-level split and external validation were not checked.",
            target="self_reported_pain",
            role="human_validation",
            risks=["metadata_only", "missing_cross_subject_validation"],
            claim="The indexed article proposes multimodal expert models for pain-score regression in postoperative children.",
        ),
        "S035": canonical(
            "S035",
            "verified_metadata",
            "ModMix: Data Augmentation for Multimodal Pain Detection",
            "https://doi.org/10.1007/978-3-031-88220-3_11",
            doi="10.1007/978-3-031-88220-3_11",
            authors="Mehmet Erdal; Sascha Gruss; Steffen Walter; Friedhelm Schwenker",
            source="ICPR Workshops and Challenges",
            note="Bibliographic identity is confirmed; full-text claims, split design and augmentation gains were not independently checked.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["metadata_only", "missing_cross_subject_validation"],
            claim="The ICPR workshop paper concerns data augmentation for multimodal pain detection.",
        ),
        "S191": canonical(
            "S191",
            "verified_primary",
            "Twins-PainViT: Towards a Modality-Agnostic Vision Transformer Framework for Multimodal Automatic Pain Assessment Using Facial Videos and fNIRS",
            "https://arxiv.org/abs/2407.19809",
            doi="10.1109/ACIIW63320.2024.00007",
            authors="Stefanos Gkikas; Manolis Tsiknakis",
            source="ACIIW 2024 / arXiv",
            note="AI4PAIN benchmark paper reporting 46.76% multilevel accuracy. This is benchmark evidence, not independent clinical validation.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["missing_cross_subject_validation"],
            claim="The paper evaluates a dual-ViT modality-agnostic fusion framework using facial video and fNIRS in the AI4PAIN challenge.",
        ),
        "S302": alias(
            "S302", "S191", "Twins-PainViT (extended)", "https://arxiv.org/abs/2407.19809"
        ),
        "S027": canonical(
            "S027",
            "verified_primary",
            "Drosophila pain sensitization and modulation unveiled by a novel pain model and analgesic drugs",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC9934396/",
            doi="10.1371/journal.pone.0281874",
            authors="Wijeong Jang; Myungsok Oh; Eun-Hee Cho; Minwoo Baek; Changsoo Kim",
            source="PLOS ONE",
            note="The assay uses transgenic TRPV1 expression, capsaicin exposure, behavior and survival. The authors use pain terminology, but these observables remain nociceptive and protective responses and cannot establish subjective human pain equivalence.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The fly assay links capsaicin activation of transgenic nociceptors to behavioral and survival effects modulated by several analgesic classes.",
        ),
        "S048": canonical(
            "S048",
            "verified_primary",
            "Selective peripheral nerve recording using simulated human median nerve activity and convolutional neural networks",
            "https://pubmed.ncbi.nlm.nih.gov/38062509/",
            doi="10.1186/s12938-023-01181-0",
            authors="Taseen Jawad; Ryan G L Koh; Jose Zariffa",
            source="BioMedical Engineering OnLine",
            note="The neural activity is generated from a finite-element model of a human median nerve; it concerns source classification for neural interfaces, not pain or ECAP/SCS outcomes.",
            target="not_applicable",
            role="method_baseline",
            risks=["synthetic_only"],
            claim="The study evaluates CNN classification of simulated nerve compound action potentials from a human median-nerve geometry under varying noise and source counts.",
        ),
        "S013": rejected(
            "S013",
            "Beyond Reflex: Nociception, Neural Circuits, and the Transformation of Threat into Memory in Drosophila melanogaster",
            "https://scholar.google.com/scholar?q=%22Beyond+Reflex%22+Nociception+Drosophila",
            "No dissertation, journal article or repository record with this exact title and stable identifier was found.",
        ),
        "S020": alias(
            "S020",
            "S150",
            "Real-time detection of gait phase for closed-loop neuromodulation with Federated Learning",
            "https://scholar.google.com/scholar?q=%22gait+phase%22+%22federated+learning%22+neuromodulation",
        ),
        "S038": alias(
            "S038",
            "S149",
            "Synthetic pain generation framework (Zero-shot)",
            "https://doi.org/10.3389/frai.2026.1827727",
        ),
        "S041": alias(
            "S041",
            "S150",
            "Real-time detection of gait phase for closed-loop neuromodulation with FL",
            "https://scholar.google.com/scholar?q=%22gait+phase%22+%22federated+learning%22+neuromodulation",
        ),
        "S050": alias(
            "S050",
            "S150",
            "Real-time detection of gait phase for closed-loop neuromodulation with FL",
            "https://scholar.google.com/scholar?q=%22gait+phase%22+%22federated+learning%22+neuromodulation",
        ),
        "S052": alias(
            "S052",
            "S149",
            "Zero-shot multimodal pain estimation via synthetic pain simulation",
            "https://doi.org/10.3389/frai.2026.1827727",
        ),
        "S075": canonical(
            "S075",
            "verified_primary",
            "Deep Learning and Noninvasive Sensors for Detecting Physiological Dysregulation: A Scoping Review",
            "https://pubmed.ncbi.nlm.nih.gov/41615529/",
            doi="10.1007/s10916-025-02332-7",
            authors="Mariana Gonzalez Garces; Jeronimo Cardenas Montoya; Maria Isabel Pena Martinez; Juanita Valencia Garcia; Erwin Hernando Hernandez Rincon",
            source="Journal of Medical Systems",
            note="Scoping review of 27 heterogeneous studies spanning pain, stress and hemodynamic deterioration; it explicitly calls for real-world and clinical-impact validation and is not effectiveness evidence.",
            target="technical_signal_quality",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The scoping review maps deep-learning use with noninvasive sensors and identifies persistent external-validation and implementation gaps.",
        ),
        "S076": alias(
            "S076",
            "S200",
            "Fly brain simulation with pain feedback mechanism (DoomFly)",
            "https://github.com/nftechie/doomfly",
        ),
        "S077": rejected(
            "S077",
            "The Fly's Last Second: Welfare states in connectome simulations",
            "https://huggingface.co/datasets/Hyperstition-for-Good/Competition-Submissions/viewer/default/human_curated",
            "The exact phrase identifies a science-fiction competition submission, not a scientific source or validated welfare-state measurement.",
        ),
        "S084": canonical(
            "S084",
            "verified_primary",
            "PainControl: Identity-Preserving Pain Expression Transfer with Generative Diffusion Models",
            "https://pubmed.ncbi.nlm.nih.gov/41968302/",
            doi="10.1186/s12938-026-01561-2",
            authors="Yasamin Zarghami; Muhammad Muzammil; Vida Adeli; Hailey Reimer; Thomas Hadjistavropoulos; Babak Taati",
            source="BioMedical Engineering OnLine",
            note="Synthetic augmentation did not improve the classifier in the general regime and showed AU-intensity and temporal limitations; gains were confined to data-scarce regimes.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["synthetic_only"],
            claim="PainControl evaluates identity-preserving diffusion-based expression transfer and reports benefits chiefly when real pain-expression data are extremely scarce.",
        ),
        "S096": alias(
            "S096",
            "S150",
            "Real-time gait phase detection for closed-loop neuromodulation",
            "https://scholar.google.com/scholar?q=%22gait+phase%22+%22federated+learning%22+neuromodulation",
        ),
    }
    decisions["S090"]["updates"]["identifiers"]["pmid"] = "39095077"
    decisions["S090"]["updates"]["год"] = 2024
    decisions["S190"]["updates"]["identifiers"]["arxiv_id"] = "2507.21886"
    decisions["S027"]["updates"]["identifiers"]["pmid"] = "36795675"
    decisions["S027"]["updates"]["год"] = 2023
    decisions["S048"]["updates"]["identifiers"]["pmid"] = "38062509"
    decisions["S075"]["updates"]["identifiers"]["pmid"] = "41615529"
    decisions["S084"]["updates"]["identifiers"]["pmid"] = "41968302"
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
