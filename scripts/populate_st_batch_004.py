"""Populate the simulator, neuromorphic hardware and patent ST batch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-004.json"
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
            "ST084",
            "verified_primary",
            "https://github.com/nftechie/doomfly",
            searches(
                ("nftechie DoomFly MaleCNS validation", "https://github.com/nftechie/doomfly"),
                (
                    "DoomFly live training protocol",
                    "https://github.com/nftechie/doomfly/blob/main/docs/doom-live-training.md",
                ),
            ),
            [
                "The repository connects a retained MaleCNS graph to engineered ViZDoom visual inputs and fixed motor readouts.",
                "Its experimental rule applies artificial damage input to two PPL101 cells and modifies selected KC-to-MBON11 weights.",
            ],
            [
                "The repository explicitly reports failed visual, conditioning and survival validation gates.",
                "Artificial game damage is an engineering reinforcement signal, not a natural nociceptor model or pain label.",
                "PPL101 and MBON11 are spectator readouts and learned survival has not been demonstrated.",
            ],
            "Experimental MaleCNS-to-ViZDoom integration with explicit negative validation results and engineered reinforcement.",
            "Retain as falsifiable implementation evidence; do not cite as successful learning, pain or whole-brain emulation.",
        ),
        decision(
            "ST085",
            "verified_primary",
            "https://patents.google.com/patent/US20220323766A1/en",
            searches(
                (
                    "US20220323766A1 EEG ECAP neurostimulation",
                    "https://patents.google.com/patent/US20220323766A1/en",
                )
            ),
            [
                "The patent application describes ML processing of EEG features and embodiments combining EEG and ECAP-derived information for neurostimulation control.",
                "It defines d_EEG from pain/paresthesia-related feature distances and an embodiment where d_total combines d_EEG with I_ECAP.",
            ],
            [
                "A patent application describes claimed embodiments and is not empirical validation, clinical efficacy evidence or a released algorithm.",
                "Its pain-state EEG assumptions and combined metric require independent prospective validation.",
            ],
            "Patent prior art for EEG/ECAP-informed machine-learning control of neurostimulation.",
            "The imported equation is confirmed as an embodiment, not an established clinical method.",
        ),
        decision(
            "ST086",
            "verified_primary",
            "https://patents.google.com/patent/US10842996B2/en",
            searches(
                (
                    "US10842996B2 ECAP stimulus artifact rejection",
                    "https://patents.google.com/patent/US10842996B2/en",
                )
            ),
            [
                "The granted patent describes neural stimulation and recording for closed-loop control.",
                "One embodiment tunes an analog stimulation-artifact simulator and subtracts the artificial artifact before digital residual processing to extract ECAPs.",
            ],
            [
                "The patent is prior art, not validation of signal quality, clinical outcome or commercial implementation.",
                "Artifact rejection does not turn ECAP into a direct measure of pain.",
            ],
            "Granted patent prior art for simultaneous stimulation/recording and analog-plus-digital artifact rejection in ECAP sensing.",
            "Exact B2 identifier and artifact-rejection embodiment were confirmed.",
        ),
        decision(
            "ST017",
            "verified_primary",
            "https://github.com/brian-team/brian2",
            searches(("Brian2 official repository", "https://github.com/brian-team/brian2")),
            [
                "Brian2 is a free, open-source, clock-driven Python simulator for spiking neural networks.",
                "It supports code generation, examples, tutorials and extensible neuron/synapse equations.",
            ],
            [
                "A general simulator does not provide a FlyWire, nociception or ECAP model by itself.",
                "Project compatibility must be tested against the selected Python and accelerator stack.",
            ],
            "General-purpose, equation-oriented SNN simulator and candidate reference CPU backend.",
            "Software identity and maintained primary repository confirmed.",
        ),
        decision(
            "ST018",
            "verified_primary",
            "https://github.com/brian-team/brian2genn",
            searches(
                ("Brian2GeNN official repository", "https://github.com/brian-team/brian2genn")
            ),
            [
                "Brian2GeNN is a Brian2 backend interface for running supported models through GeNN on NVIDIA GPUs."
            ],
            [
                "The maintainers label the software beta.",
                "The imported 10-100x speedup is not a universal guarantee and was removed; performance depends on model and hardware.",
                "The current GeNN project also supports AMD HIP, but Brian2GeNN's documented path is NVIDIA-focused.",
            ],
            "Beta Brian2-to-GeNN backend for accelerator execution of supported SNN simulations.",
            "Benchmark claims must be reproduced on the chosen whole-brain workload.",
        ),
        decision(
            "ST019",
            "verified_primary",
            "https://github.com/genn-team/genn",
            searches(("GeNN official repository CUDA HIP", "https://github.com/genn-team/genn")),
            [
                "GeNN is a code-generation environment for neuronal-network simulation on NVIDIA CUDA and AMD HIP accelerators."
            ],
            [
                "It is a simulation engine, not a biological model or dataset.",
                "Supported model features and device memory limits require workload-specific testing.",
            ],
            "GPU-accelerated neuronal-network simulation environment based on generated CUDA/HIP code.",
            "Exact maintained repository replaces the former documentation-domain landing page.",
        ),
        decision(
            "ST020",
            "verified_primary",
            "https://github.com/nest/nest-simulator",
            searches(
                ("NEST Simulator official repository", "https://github.com/nest/nest-simulator")
            ),
            [
                "NEST is an open-source simulator for the dynamics, size and structure of spiking neuronal networks.",
                "It exposes Python and standalone interfaces and scales from laptops to compute clusters.",
            ],
            [
                "NEST focuses on network dynamics rather than exact single-neuron morphology.",
                "No FlyWire, nociception or ECAP model is supplied by the framework itself.",
            ],
            "Scalable point-neuron/network simulator and candidate independent backend for reproducibility checks.",
            "Exact maintained repository and project scope confirmed.",
        ),
        decision(
            "ST021",
            "verified_primary",
            "https://github.com/cplab/sapicore",
            searches(("cplab sapicore", "https://github.com/cplab/sapicore")),
            [
                "sapicore is a public PyTorch-based framework for neuromorphic modeling with documentation and tutorials."
            ],
            [
                "Repository metadata alone does not establish biological realism or suitability for a 100k-neuron connectome.",
                "Activity is lower than the major general-purpose simulators and local execution has not been tested.",
            ],
            "PyTorch-based neuromorphic-modeling framework for prototype comparison.",
            "Retain as a candidate only after scale and reproducibility benchmarking.",
        ),
        decision(
            "ST022",
            "verified_primary",
            "https://github.com/NeuromorphicProcessorProject/snn_toolbox",
            searches(
                (
                    "SNN Toolbox ANN to SNN official repository",
                    "https://github.com/NeuromorphicProcessorProject/snn_toolbox",
                )
            ),
            [
                "The toolbox converts analog neural networks to spiking networks and runs them in supported spiking simulators."
            ],
            [
                "Its primary use is ANN-to-SNN conversion, not connectome-constrained biological simulation.",
                "The repository's last source push predates this audit by several years, so current dependency compatibility requires testing.",
            ],
            "ANN-to-SNN conversion toolbox for deployment experiments, not a FlyBrain simulator.",
            "Scope narrowed to the functionality stated by the repository.",
        ),
        decision(
            "ST023",
            "verified_primary",
            "https://github.com/norse/norse",
            searches(("Norse PyTorch SNN official repository", "https://github.com/norse/norse")),
            [
                "Norse extends PyTorch with differentiable spiking-neuron components and provides notebooks, tasks and examples."
            ],
            [
                "The library targets trainable deep SNNs and does not supply connectome or biological-validation data.",
                "Repository performance statements are preliminary and workload-specific.",
            ],
            "Differentiable PyTorch SNN component library for trainable baseline models and representation experiments.",
            "Do not infer biological fidelity from bio-inspired components.",
        ),
        decision(
            "ST024",
            "verified_primary",
            "https://github.com/jeshraghian/snntorch",
            searches(("snnTorch official repository", "https://github.com/jeshraghian/snntorch")),
            [
                "snnTorch provides gradient-based SNN learning integrated with PyTorch/autograd, surrogate gradients and NIR import/export."
            ],
            [
                "It is a machine-learning library, not a biophysical connectome simulator.",
                "GPU acceleration and feasible scale inherit PyTorch and require empirical benchmarking.",
            ],
            "PyTorch library for gradient-based SNN baselines, training and interchange experiments.",
            "Relevant to model comparison, not evidence for fly-to-human transfer.",
        ),
        decision(
            "ST025",
            "partially_verified",
            "https://doi.org/10.1145/3730581",
            searches(
                ("ModNEF modular neuromorphic emulator FPGA", "https://doi.org/10.1145/3730581"),
                ("github ModNEF", "https://github.com/ModNEF"),
            ),
            [
                "The ACM article describes ModNEF as a modular open-source FPGA SNN emulator evaluated on a Xilinx Zynq device with MNIST/N-MNIST."
            ],
            [
                "The imported GitHub organization URL returns 404 and no stable source repository was confirmed.",
                "The paper does not establish support for whole-connectome scale, biological models or the project's target hardware.",
            ],
            "Published FPGA SNN-emulator architecture whose reusable source location remains unverified.",
            "Keep as hardware prior art, not as an immediately available implementation dependency.",
        ),
        decision(
            "ST026",
            "verified_primary",
            "https://doc.brainchipinc.com/",
            searches(("BrainChip MetaTF official documentation", "https://doc.brainchipinc.com/")),
            [
                "MetaTF bundles Python packages for creating, converting, simulating and deploying networks on the Akida platform.",
                "The official getting-started guide documents pip installation and a software simulator.",
            ],
            [
                "BrainChip states that examples are Apache-licensed but the underlying Akida library is proprietary under an EULA.",
                "This is a deployment SDK and simulator, not open biological-neural simulation software.",
            ],
            "Proprietary-core Akida development framework with Python APIs, conversion tools and a software simulator.",
            "Licensing must be reviewed before reproducible dissertation artifacts depend on it.",
        ),
        decision(
            "ST027",
            "partially_verified",
            "https://brainchip.com/wp-content/uploads/2025/04/AKD1000-Edge-AI-Box-Product-Brochure-V.2-Mar.-25.pdf",
            searches(
                (
                    "BrainChip Edge AI Box official product brief",
                    "https://brainchip.com/wp-content/uploads/2025/04/AKD1000-Edge-AI-Box-Product-Brochure-V.2-Mar.-25.pdf",
                )
            ),
            [
                "The official product brief describes an Edge AI Box with an NXP i.MX 8M Plus and two AKD1000 accelerators."
            ],
            [
                "The checked Edge AI Box is AKD1000-based; the imported AKD1000/AKD1500 wording was not confirmed.",
                "It is commercial deployment hardware, not required for dataset or simulator validity.",
            ],
            "Commercial AKD1000 Edge AI Box for Akida edge-inference demonstrations.",
            "Hardware purchase is optional and must follow a measured software-only feasibility comparison.",
        ),
        decision(
            "ST028",
            "partially_verified",
            "https://brainchip.com/press/brainchip-launches-akd1500-pcie-card-for-edge-ai-evaluation-everywhere/",
            searches(
                (
                    "BrainChip AKD1500 official open tools",
                    "https://brainchip.com/press/brainchip-launches-akd1500-pcie-card-for-edge-ai-evaluation-everywhere/",
                ),
                ("BrainChip DevHub AKD1500", "https://github.com/Brainchip-Inc/brainchip_devhub"),
            ),
            [
                "BrainChip markets AKD1500 silicon and PCIe/M.2 evaluation hardware and publishes example projects in DevHub.",
                "The official material states that tools/model examples are available without subscription fees.",
            ],
            [
                "AKD1500 hardware and the underlying Akida runtime are not established as open-source; the imported label is false as written.",
                "No Arduino Nicla driver claim was verified for AKD1500.",
            ],
            "Commercial AKD1500 neuromorphic accelerator with public examples and proprietary runtime components.",
            "Do not describe the chip or complete software stack as open-source.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
