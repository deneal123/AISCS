"""Populate the ML tooling, pain-model and notebook ST batch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-005.json"
TODAY = date.today().isoformat()


def searches(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"query": query, "url": url, "accessed_at": TODAY} for query, url in items]


def decision(
    resource_id: str,
    outcome: str,
    exact_url: str | None,
    searched: list[dict[str, str]],
    claims: list[str],
    limitations: list[str],
    purpose: str,
    note: str,
) -> dict:
    return {
        "resource_id": resource_id,
        "decision": outcome,
        "exact_url": exact_url,
        "checked_at": TODAY,
        "searches": searched,
        "verified_claims": claims,
        "limitations": limitations,
        "corrected_purpose": purpose,
        "note": note,
    }


def main() -> None:
    payload = load_json(PATH)
    payload["meta"].update({"status": "reviewed", "reviewed_at": TODAY})
    payload["decisions"] = [
        decision(
            "ST029",
            "verified_primary",
            "https://docs.edgeimpulse.com/hardware/boards/brainchip-akd1000",
            searches(
                (
                    "Edge Impulse BrainChip AKD1000 deployment block",
                    "https://docs.edgeimpulse.com/hardware/boards/brainchip-akd1000",
                )
            ),
            [
                "Edge Impulse documents AKD1000 deployment through BrainChip MetaTF and AKD1000 deployment blocks.",
                "The documented workflow uses the Akida Python library, Akida PCIe drivers and Edge Impulse Linux tooling.",
            ],
            [
                "The documented AKD1000 binary workflow pins Python 3.8 and Akida 2.3.3; compatibility is version-sensitive.",
                "This is a hardware deployment route, not evidence for biological fidelity, pain inference or clinical performance.",
            ],
            "Official integration documentation for deploying compatible Edge Impulse models to BrainChip AKD1000 hardware.",
            "The exact board-specific page replaces the former documentation homepage.",
        ),
        decision(
            "ST030",
            "partially_verified",
            "https://huggingface.co/Catalyst-Neuromorphic/catalyst-n1",
            searches(
                (
                    "Catalyst N1 neuromorphic processor SDK backends",
                    "https://huggingface.co/Catalyst-Neuromorphic/catalyst-n1",
                )
            ),
            [
                "The project card describes an Apache-2.0 128-core LIF neuromorphic processor, Verilog RTL, testbenches and a Python SDK.",
                "The SDK documentation lists CPU, PyTorch-CUDA GPU and FPGA backends under one API.",
            ],
            [
                "The imported 4-8x speedup is absent from the checked primary page and is removed as an unverified metric.",
                "FPGA validation and benchmark statements are self-reported; no independent reproduction was located.",
            ],
            "Candidate open neuromorphic RTL/SDK stack requiring local reproduction before use.",
            "Keep as engineering prior art, not as validated performance evidence.",
        ),
        decision(
            "ST052",
            "partially_verified",
            "https://github.com/MRausus/VST-APA",
            searches(("MRausus VST-APA", "https://github.com/MRausus/VST-APA")),
            [
                "The public repository exists and contains one Video Swin Transformer pain-detection notebook."
            ],
            [
                "The repository has one commit, no README, release, paper identifier or documented evaluation protocol.",
                "Effectiveness, generalizability and explainability claims were not confirmed and are removed.",
            ],
            "Unverified experimental notebook for Video Swin Transformer pain classification.",
            "Not suitable as evidence until code, data split, metrics and provenance are documented.",
        ),
        decision(
            "ST053",
            "partially_verified",
            "https://github.com/AnupKumarGupta/HCAT-Pain",
            searches(
                ("HCAT-Pain official repository", "https://github.com/AnupKumarGupta/HCAT-Pain")
            ),
            [
                "The authors describe a hierarchical cross-attention model using video-derived pulse, respiration and facial action units on AI4Pain data from 65 participants.",
                "The page reports multiclass and binary pain-classification results for a 2026 FG paper.",
            ],
            [
                "The repository explicitly states that implementation code has not yet been uploaded.",
                "Reported results are author-provided and were not reproduced; dataset access remains subject to its EULA.",
                "Video-derived proxies and facial behavior do not constitute a direct measure of subjective pain.",
            ],
            "Paper project page for a non-contact multimodal pain-classification method; implementation pending.",
            "Metadata and stated method are retained, but reproducibility is not established.",
        ),
        decision(
            "ST054",
            "verified_primary",
            "https://github.com/GkikasStefanos/Tiny-BioMoE",
            searches(
                (
                    "Tiny-BioMoE official repository",
                    "https://github.com/GkikasStefanos/Tiny-BioMoE",
                ),
                ("Tiny-BioMoE DOI", "https://doi.org/10.1145/3747327.3764788"),
            ),
            [
                "The repository provides MIT-licensed model code and a downloadable pretrained checkpoint.",
                "The published ICMI 2025 Companion paper is identified by DOI 10.1145/3747327.3764788.",
                "The authors describe 7.34 million parameters, 192-dimensional embeddings and pretraining across ECG, EMG and EEG representations.",
            ],
            [
                "The architecture consumes image-like signal representations and does not itself align fly and human modalities.",
                "Suitability and performance for the dissertation datasets require independent evaluation.",
            ],
            "Published lightweight biosignal embedding baseline with openly released weights.",
            "Candidate representation baseline, not evidence of cross-species transfer.",
        ),
        decision(
            "ST055",
            "verified_primary",
            "https://github.com/Satyajithchary/Hierarchical-Multimodal-Fusion-with-Phased-Training-for-X-ITE-Challenge",
            searches(
                (
                    "Hierarchical Multimodal Fusion X-ITE official implementation",
                    "https://github.com/Satyajithchary/Hierarchical-Multimodal-Fusion-with-Phased-Training-for-X-ITE-Challenge",
                )
            ),
            [
                "The repository contains code for physiological, four-video-stream and audio fusion with a three-phase training procedure.",
                "It reports a held-out test accuracy of 49.7%, macro F1 of 34.0% and ROC AUC of 0.533 on the binary X-ITE task.",
            ],
            [
                "The reported result is near chance and predicts the high-pain class with only 1% recall.",
                "The repository's claim that this behavior is clinically desirable is not supported by the reported discrimination metrics.",
                "Code availability does not establish generalization or clinical utility.",
            ],
            "Reproducible negative/weak baseline for multimodal X-ITE experiments and failure analysis.",
            "Retain for architecture and ablation comparison; do not cite as effective pain recognition.",
        ),
        decision(
            "ST056",
            "verified_primary",
            "https://doi.org/10.1371/journal.pdig.0001424",
            searches(
                (
                    "Cross-spectral fusion thermal RGB pain PLOS",
                    "https://doi.org/10.1371/journal.pdig.0001424",
                ),
                (
                    "CSAF official code",
                    "https://github.com/oussama123-ai/Cross-Spectral-Fusion-of-Thermal",
                ),
            ),
            [
                "The peer-reviewed PLOS Digital Health article evaluates synchronized thermal and RGB video in 50 healthy adults and 30 postoperative adults.",
                "The authors report combined-cohort MAE 0.87 versus 1.23 for the RGB-only baseline and provide code plus split metadata.",
                "The target is participant-reported 0-10 NRS, with controlled and postoperative cohorts analyzed separately and together.",
            ],
            [
                "Validation is adult-only, single-team and not an external multi-site prospective clinical validation.",
                "Five-fold results and author-reported metrics require independent reproduction before model selection.",
                "Thermal/RGB estimates of NRS are not a direct physiological measurement of pain.",
            ],
            "Primary multimodal human-pain study and codebase for thermal-plus-RGB comparison, DOI 10.1371/journal.pdig.0001424.",
            "Use the article, not the repository wording, as the primary evidence source.",
        ),
        decision(
            "ST057",
            "verified_primary",
            "https://doi.org/10.1109/TAFFC.2025.3605475",
            searches(
                ("PainFormer official repository", "https://github.com/GkikasStefanos/PainFormer"),
                ("PainFormer DOI", "https://doi.org/10.1109/TAFFC.2025.3605475"),
            ),
            [
                "PainFormer is published in IEEE Transactions on Affective Computing under DOI 10.1109/TAFFC.2025.3605475.",
                "The official repository releases MIT-licensed code and a pretrained checkpoint and reports pretraining on 14 tasks with 10.9 million samples.",
            ],
            [
                "The scale values are author-reported and do not imply independent subjects or pain-specific samples.",
                "It is a vision foundation model and does not validate physiological or cross-species transfer claims.",
            ],
            "Published vision representation baseline for human facial/affective and pain-assessment tasks.",
            "Retain as a comparator for human video representations only.",
        ),
        decision(
            "ST058",
            "partially_verified",
            "https://github.com/LorenzoGianassi/Automatic-Recognition-VAS-Index-with-Random-Forest",
            searches(
                (
                    "Automatic Recognition VAS Index Random Forest",
                    "https://github.com/LorenzoGianassi/Automatic-Recognition-VAS-Index-with-Random-Forest",
                )
            ),
            [
                "The course-project repository implements a Random Forest regressor for facial-landmark features and supports UNBC and BioVid inputs.",
                "Its configuration exposes leave-one-subject-out, five-fold and leave-one-sequence-out evaluation modes.",
            ],
            [
                "No peer-reviewed publication or stable dataset redistribution license is documented.",
                "The README does not establish a validated performance advantage and linked dataset mirrors may not be authoritative.",
            ],
            "Exploratory classical-ML implementation for facial-feature pain-score regression.",
            "Use only as implementation prior art after replacing dataset links with official access routes.",
        ),
        decision(
            "ST059",
            "verified_primary",
            "https://github.com/pytorch-tabular/pytorch_tabular",
            searches(
                (
                    "PyTorch Tabular official repository",
                    "https://github.com/pytorch-tabular/pytorch_tabular",
                )
            ),
            [
                "PyTorch Tabular is an MIT-licensed framework with a unified API for deep-learning models on tabular data.",
                "It includes classification/regression models, tutorials, tests, logging integrations and PyTorch Lightning-based training.",
            ],
            [
                "It is general-purpose infrastructure and supplies no pain-specific evidence or validation protocol.",
                "The imported repository URL redirects to the current pytorch-tabular organization.",
            ],
            "Optional framework for structured-feature baselines and experiment plumbing.",
            "Do not treat library model availability as evidence of suitability for this corpus.",
        ),
        decision(
            "ST060",
            "verified_primary",
            "https://github.com/sktime/sktime",
            searches(("sktime official repository", "https://github.com/sktime/sktime")),
            [
                "sktime is a BSD-licensed time-series library supporting classification, regression, forecasting, clustering and validation utilities."
            ],
            [
                "The library is not pain-specific; the imported phrase 'pain detection' is removed.",
                "Participant-level grouping and leakage controls must be implemented explicitly in project experiments.",
            ],
            "General time-series baseline and pipeline library for physiological-signal experiments.",
            "Candidate tooling only, with project-specific grouped evaluation required.",
        ),
        decision(
            "ST061",
            "verified_primary",
            "https://github.com/Lightning-AI/lightning",
            searches(
                (
                    "PyTorch Lightning official repository",
                    "https://github.com/Lightning-AI/lightning",
                )
            ),
            [
                "The official Lightning repository provides PyTorch Lightning for structured training loops, accelerator/distributed execution and logging."
            ],
            [
                "It is engineering infrastructure, not a model, scientific method or validation result.",
                "Reproducibility still requires pinned environments, seeds, dataset versions and saved split manifests.",
            ],
            "Training-loop and experiment-infrastructure candidate for reproducible PyTorch baselines.",
            "Exact current repository replaces the former redirected pytorch-lightning URL.",
        ),
        decision(
            "ST069",
            "verified_primary",
            "https://research.google.com/colaboratory/faq.html",
            searches(
                (
                    "Google Colab official FAQ GPU TPU limits",
                    "https://research.google.com/colaboratory/faq.html",
                )
            ),
            [
                "Google describes Colab as a hosted Jupyter service with a no-charge tier and optional GPU/TPU runtimes."
            ],
            [
                "Resources, accelerator types, usage limits and runtime duration are not guaranteed and change over time.",
                "The free tier commonly permits at most 12-hour sessions and is unsuitable as the sole reproducibility environment.",
                "Colab does not itself provide SNN tutorials; those belong to separate projects.",
            ],
            "Convenience notebook environment for demonstrations and smoke tests, not guaranteed experiment infrastructure.",
            "The exact FAQ is the primary source for availability and limit claims.",
        ),
        decision(
            "ST070",
            "verified_primary",
            "https://github.com/norse/notebooks",
            searches(("Norse notebook tutorials official", "https://github.com/norse/notebooks")),
            [
                "The Norse project provides public introductory, supervised-learning, event-processing and neuroscience notebooks.",
                "The repository states that notebooks can run in Colab and that local/Colab environments may use hardware acceleration.",
            ],
            [
                "Browser-hosted execution uses CPU and may be slow for larger networks.",
                "TPU compatibility is not demonstrated per notebook and Colab accelerator access is not guaranteed.",
                "Tutorials are educational examples, not project benchmarks or biological validation.",
            ],
            "Educational Norse notebooks and smoke-test examples for differentiable SNN workflows.",
            "Retain GPU/TPU wording only as an environment option, not a tested guarantee.",
        ),
        decision(
            "ST071",
            "verified_primary",
            "https://github.com/jeshraghian/snntorch",
            searches(
                ("snnTorch official tutorials Colab", "https://github.com/jeshraghian/snntorch")
            ),
            [
                "The official repository links a Colab quickstart, examples and a tutorial series for gradient-based SNN learning.",
                "snnTorch uses PyTorch autograd and can use CUDA when models and tensors are placed on a compatible GPU.",
            ],
            [
                "The exact imported count of '5+ Colab tutorials' is not a stable software property and is removed.",
                "Colab availability and accelerator assignment are controlled by Google and are not guaranteed.",
                "Tutorial completion does not validate whole-connectome scale or biological realism.",
            ],
            "Educational snnTorch quickstart/tutorial material for baseline prototyping.",
            "The resource overlaps ST024 but is retained as a distinct training-material role.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
