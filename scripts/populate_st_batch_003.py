"""Populate the SCS models, clinical evidence and bridge-evidence ST batch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-003.json"
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
            "ST049",
            "rejected",
            None,
            searches(
                (
                    "site:figshare.com data_CL_SCS postural ECAP",
                    "https://figshare.com/search?q=data_CL_SCS",
                )
            ),
            [],
            [
                "No exact Figshare record, DOI or primary page matching data_CL_SCS and the imported postural-ECAP description was found."
            ],
            "Rejected dataset candidate without a stable identifier or primary record.",
            "Do not treat the imported ECAP/posture description as an available dataset.",
        ),
        decision(
            "ST050",
            "rejected",
            None,
            searches(
                (
                    "site:figshare.com ECAP conductivity directional contacts SCS",
                    "https://figshare.com/search?q=ECAP%20conductivity%20SCS",
                )
            ),
            [],
            [
                "No exact Figshare record or DOI matching the claimed combination of ECAP amplitudes, directional contacts and tissue conductivity was found."
            ],
            "Rejected dataset candidate without a stable identifier or verified composition.",
            "A general Figshare domain cannot substantiate availability or contents.",
        ),
        decision(
            "ST051",
            "partially_verified",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12803051/",
            searches(
                (
                    "Newcastle epidural spinal recordings ECAP doublet ESAP EMG",
                    "https://pmc.ncbi.nlm.nih.gov/articles/PMC12803051/",
                )
            ),
            [
                "The publication characterizes ECAPs, doublets, ESAPs and EMG in preclinical epidural spinal recordings."
            ],
            [
                "The checked source is a preclinical publication, not a confirmed openly downloadable human dataset.",
                "Species and recording geometry limit direct use for human SCS outcome prediction.",
            ],
            "Preclinical publication on electrophysiological components and artifacts in epidural spinal recordings.",
            "Retained as measurement-model evidence, not as an available validation dataset.",
        ),
        decision(
            "ST062",
            "verified_primary",
            "https://zenodo.org/records/3732197",
            searches(("RADO-SCS Zenodo", "https://zenodo.org/records/3732197")),
            [
                "Zenodo DOI 10.5281/zenodo.3732197 provides RADO-SCS 3.0 CAD/STL anatomy for T9-T11 and clinical leads.",
                "The record documents a 0.1-mm anatomical representation and a FEM-to-axon modeling workflow.",
            ],
            [
                "RADO-SCS is a CAD-derived model resource, not executable SCS modeling software.",
                "It does not include pathological or patient-specific spinal anatomy.",
            ],
            "Open CAD/STL anatomical resource for constructing conventional, high-frequency, DRG and trans-spinal stimulation models.",
            "Exact Zenodo record and model/software distinction were confirmed.",
        ),
        decision(
            "ST063",
            "verified_primary",
            "https://github.com/jostrows9/SCSInSCIMechanisms",
            searches(
                ("jostrows9 SCSInSCIMechanisms", "https://github.com/jostrows9/SCSInSCIMechanisms")
            ),
            [
                "Repository contains NEURON simulation and EMG-analysis code underlying Balaguer et al. (2025).",
                "It models interaction of epidural SCS, supraspinal input and motoneuron pools after spinal injury.",
            ],
            [
                "The model addresses motor control after spinal-cord injury, not chronic-pain relief or ECAP prediction.",
                "Local reproducibility and parameter provenance were not independently tested.",
            ],
            "NEURON-based biophysical SCS model and analysis code for motor-circuit mechanisms after spinal-cord injury.",
            "Relevant as mechanistic software, not as a pain-outcome model.",
        ),
        decision(
            "ST064",
            "verified_primary",
            "https://github.com/lauramedlock/SCS-network",
            searches(
                (
                    "lauramedlock SCS-network Sagalajev",
                    "https://github.com/lauramedlock/SCS-network",
                )
            ),
            [
                "Repository provides NEURON/NetPyNE code intended to reproduce the SCS network model from Sagalajev et al.",
                "The README links DOI 10.1016/j.neuron.2023.10.021.",
            ],
            [
                "The repository is small and has no release package or automated reproducibility evidence.",
                "Its pain-suppression mechanism is a model hypothesis, not a clinical-outcome predictor.",
            ],
            "NEURON/NetPyNE implementation of a published spinal-cord-stimulation network model.",
            "Execution and numerical reproduction remain a later feasibility gate.",
        ),
        decision(
            "ST065",
            "verified_primary",
            "https://github.com/nrv-framework/NRV",
            searches(("NRV NeuRon Virtualizer", "https://github.com/nrv-framework/NRV")),
            [
                "NRV is an actively developed Python library for peripheral nervous-system stimulation modeling.",
                "The repository includes documentation, examples, tests and tutorials.",
            ],
            [
                "NRV targets peripheral nerves and is not a ready-made spinal-cord or ECAP model.",
                "Its redirected organization URL should replace the former personal-repository URL.",
            ],
            "General multiscale Python framework for in-silico peripheral-nerve stimulation.",
            "Potential component only; spinal-cord applicability requires a separate model.",
        ),
        decision(
            "ST066",
            "verified_primary",
            "https://github.com/OpenMedTech-Lab/OpenXstim",
            searches(
                (
                    "OpenMedTech OpenXstim programmable transcutaneous stimulator",
                    "https://github.com/OpenMedTech-Lab/OpenXstim",
                )
            ),
            [
                "Repository publishes an open design for a programmable transcutaneous current stimulator."
            ],
            [
                "This is stimulation hardware, not a validated SCS simulator, dataset or clinical device.",
                "Safety, regulatory status and suitability for any human experiment are not established by the repository.",
            ],
            "Open programmable transcutaneous current-stimulator hardware design for engineering reference only.",
            "Not authorized here for human use or self-experimentation.",
        ),
        decision(
            "ST067",
            "verified_primary",
            "https://www.nature.com/articles/s44385-026-00076-8",
            searches(
                (
                    "npj biophysical surrogate digital twins neural interfaces",
                    "https://www.nature.com/articles/s44385-026-00076-8",
                )
            ),
            [
                "The 2026 review describes hybrid volume-conduction, neural-response and transduction models plus surrogate optimization.",
                "It surveys SCS among several neuroprosthetic applications and identifies calibration and personalization limits.",
            ],
            [
                "This is a review and conceptual framework, not a released SCS digital-twin implementation or dataset.",
                "The paper notes that subject-specific calibration remains early and assumptions are substantial.",
            ],
            "Review framework for biophysical and surrogate digital twins used to optimize neural interfaces, including SCS.",
            "Use for modeling requirements and limitations, not implementation evidence.",
        ),
        decision(
            "ST068",
            "verified_primary",
            "https://www.pdh.med.fau.de/research/neural-engineering/epidural-spinal-cord-stimulation/",
            searches(
                (
                    "FAU multiscale digital twins spinal cord Pareto",
                    "https://www.pdh.med.fau.de/research/neural-engineering/epidural-spinal-cord-stimulation/",
                )
            ),
            [
                "The FAU project page states an aim to create multiscale spinal-cord digital twins and explore Pareto-optimal parameter solutions."
            ],
            [
                "The page describes an ongoing research direction and provides no validated software, dataset or clinical results.",
                "No patient-specific pain or ECAP prediction claim is supported.",
            ],
            "FAU research-program page on multiscale spinal-cord digital twins and Pareto-oriented eSCS design.",
            "Treat as prospective prior art, not a reusable artifact.",
        ),
        decision(
            "ST079",
            "verified_primary",
            "https://www.nature.com/articles/s41592-025-02988-6",
            searches(
                (
                    "Nature Methods Method of the Year 2025 EM connectomics",
                    "https://www.nature.com/articles/s41592-025-02988-6",
                )
            ),
            [
                "Nature Methods selected electron-microscopy-based connectomics as Method of the Year 2025.",
                "The editorial discusses whole-brain Drosophila/FlyWire and other connectomics achievements.",
            ],
            [
                "The award is for EM-based connectomics broadly, not for FlyWire alone.",
                "An editorial distinction is not validation of a particular simulator or pain-transfer hypothesis.",
            ],
            "Editorial context for EM-based connectomics and the methodological significance of FlyWire-scale reconstructions.",
            "Resource title was broader than the verified editorial scope and is corrected in purpose.",
        ),
        decision(
            "ST080",
            "verified_primary",
            "https://www.nature.com/articles/s41586-024-07763-9",
            searches(
                (
                    "Shiu Drosophila computational brain model Nature 2024",
                    "https://www.nature.com/articles/s41586-024-07763-9",
                )
            ),
            [
                "The article implements a Brian2 LIF model of 127,400 central-brain neurons using FlyWire connectivity and transmitter identity.",
                "Feeding and grooming predictions were tested with optogenetics, imaging and behaviour; one unbiased cell-type screen exceeded 90% accuracy.",
            ],
            [
                "The greater-than-90% result is task- and screen-specific, not 91% whole-brain prediction accuracy.",
                "The authors note zero baseline firing, missing neuromodulation and inaccurate absolute firing-rate assumptions.",
            ],
            "Primary whole-central-brain LIF model for experimentally testable feeding and grooming sensorimotor circuits.",
            "The imported global 91% accuracy claim was narrowed to the actual evaluation.",
        ),
        decision(
            "ST081",
            "partially_verified",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC11103285/",
            searches(
                (
                    "EVOKE closed-loop open-loop SCS 36 month trial",
                    "https://pmc.ncbi.nlm.nih.gov/articles/PMC11103285/",
                ),
                ("JPHV EVOKE RR 1.47 2026", "https://www.jphv.org/"),
            ),
            [
                "The EVOKE blinded randomized trial NCT02924129 compared ECAP-controlled closed-loop with fixed-output open-loop SCS.",
                "At 36 months the publication reports 77.6% versus 49.3% achieving at least 50% overall back/leg pain reduction.",
            ],
            [
                "The imported JPHV 2026 pooled-analysis identity was not confirmed as a stable primary publication.",
                "The RR 1.47 figure must not replace the directly reported time-specific trial results and confidence intervals.",
            ],
            "Primary EVOKE randomized-trial evidence for ECAP-controlled closed-loop versus open-loop SCS.",
            "Underlying trial verified; the imported secondary-publication attribution remains unverified.",
        ),
        decision(
            "ST082",
            "verified_primary",
            "https://www.neuromodulationjournal.org/article/S1094-7159%2825%2901170-5/fulltext",
            searches(
                (
                    "Control Signals Closed-Loop SCS scoping review",
                    "https://www.neuromodulationjournal.org/article/S1094-7159%2825%2901170-5/fulltext",
                )
            ),
            [
                "The scoping review screened 688 unique articles and retained 28 publications covering 19 unique studies.",
                "It categorized three subjective-state, seven position/movement and nine ECAP-control studies and found no fully integrated subjective-plus-biophysical model.",
            ],
            [
                "The result is a literature-gap statement, not proof that such integration improves outcomes.",
                "ECAP is treated as spinal activation and a proxy for delivery changes, not direct pain intensity.",
            ],
            "Scoping review of control signals used in closed-loop SCS for chronic pain.",
            "Exact DOI 10.1016/j.neurom.2025.11.011 and counts were confirmed.",
        ),
        decision(
            "ST083",
            "partially_verified",
            "https://eon.systems/updates/embodied-brain-emulation",
            searches(
                (
                    "Eon embodied brain emulation Drosophila NeuroMechFly",
                    "https://eon.systems/updates/embodied-brain-emulation",
                )
            ),
            [
                "Eon describes integration of a FlyWire-derived LIF brain model with a NeuroMechFly/MuJoCo body.",
                "The page identifies the work as an integration of existing brain and body models and discusses roughly 140,000 neurons and 50 million synapses.",
            ],
            [
                "The source is a company-authored demonstration, not peer-reviewed independent validation of embodied whole-brain emulation.",
                "The demonstrated behaviours and brain-body interface require code, protocol and ablation review before scientific use.",
            ],
            "Company technical account of an experimental FlyWire-LIF and NeuroMechFly/MuJoCo integration.",
            "Do not cite it as validated brain upload, nociception model or emergent-behaviour evidence.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
