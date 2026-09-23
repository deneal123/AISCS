"""Populate the final tutorial and proposed-system-requirement ST batch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-006.json"
TODAY = date.today().isoformat()


def searches(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"query": q, "url": u, "accessed_at": TODAY} for q, u in items]


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


def rejected_requirement(resource_id: str, imported: str) -> dict:
    reference_urls = {
        "ST087": "https://github.com/brian-team/brian2",
        "ST088": "https://www.nature.com/articles/s41586-024-07763-9",
        "ST089": "https://github.com/brian-team/brian2genn",
        "ST090": "https://github.com/seung-lab/FlyConnectome",
        "ST093": "https://github.com/brian-team/brian2genn",
        "ST094": "https://github.com/nest/nest-simulator",
        "ST095": "https://www.nature.com/articles/s41586-024-07763-9",
    }
    reference_url = reference_urls[resource_id]
    return decision(
        resource_id,
        "rejected",
        None,
        searches((f"primary documentation supporting {imported}", reference_url)),
        [],
        [
            f"The imported requirement ({imported}) has no workload benchmark, dependency lock or primary source.",
            "A hardware estimate cannot be validated before a representative simulator and dataset pipeline are benchmarked.",
        ],
        "Superseded planning estimate; replace with measured peak memory, runtime, storage and compatibility results.",
        "Rejected as an evidence resource, not asserted to be technically impossible.",
    )


def main() -> None:
    payload = load_json(PATH)
    payload["meta"].update({"status": "reviewed", "reviewed_at": TODAY})
    payload["decisions"] = [
        decision(
            "ST072",
            "partially_verified",
            "https://github.com/google/evojax",
            searches(("EvoJAX official repository SNN Colab", "https://github.com/google/evojax")),
            [
                "EvoJAX is an Apache-licensed JAX neuroevolution toolkit with notebook examples and optional GPU/TPU execution.",
                "The project notes that Colab includes JAX and provides notebooks under its examples tree.",
            ],
            [
                "No exact EvoJAX SNN Colab notebook matching the imported title was confirmed.",
                "The Google repository was archived in August 2025 and is read-only.",
                "General neuroevolution support does not establish a biologically grounded SNN simulator.",
            ],
            "Archived general JAX neuroevolution toolkit; no verified project-specific SNN notebook.",
            "The generic nbviewer link is replaced, but the imported SNN-specific identity remains unconfirmed.",
        ),
        decision(
            "ST073",
            "partially_verified",
            "https://github.com/adiehl96/SNN-computing",
            searches(
                ("Radboud SNN Simulator repository", "https://github.com/adiehl96/SNN-computing")
            ),
            [
                "The MIT-licensed repository contains an SNN simulator example notebook and a Colab badge."
            ],
            [
                "The checked GitHub repository is a fork and explicitly labels itself legacy.",
                "Maintenance moved to a Radboud GitLab instance; the current upstream contents and reproducibility were not verified.",
                "No evidence establishes scalability to the target connectome.",
            ],
            "Legacy educational SNN notebook whose maintained upstream must be checked before reuse.",
            "Do not select it over maintained simulators without a local benchmark.",
        ),
        decision(
            "ST074",
            "verified_primary",
            "https://github.com/seung-lab/FlyConnectome/blob/main/CAVE%20tutorial.ipynb",
            searches(
                (
                    "FlyConnectome CAVE tutorial official notebook",
                    "https://github.com/seung-lab/FlyConnectome/blob/main/CAVE%20tutorial.ipynb",
                )
            ),
            [
                "The Seung Lab FlyConnectome repository contains a 4,045-line CAVE tutorial notebook for programmatic connectome access."
            ],
            [
                "The notebook documents data access, not neuronal dynamics, nociception or simulation validity.",
                "Authentication, materialization version and API outputs must be pinned in any reproducible extraction.",
            ],
            "Primary tutorial for programmatic CAVE/FlyConnectome data access.",
            "Use with an explicit materialization/version manifest.",
        ),
        decision(
            "ST076",
            "verified_primary",
            "https://genn-team.github.io/genn/documentation/3/html/d3/d0c/brian2genn.html",
            searches(
                (
                    "Brian2GeNN LIF f/I tutorial",
                    "https://genn-team.github.io/genn/documentation/3/html/d3/d0c/brian2genn.html",
                )
            ),
            [
                "The GeNN documentation gives a Brian2GeNN LIF example with varying input currents to construct an f/I curve.",
                "It documents switching Brian2 to the GeNN device and configuring GeNN/CUDA paths.",
            ],
            [
                "The page belongs to older GeNN 3 documentation and is an API example, not a current performance benchmark.",
                "The example is too small to demonstrate benefit from GPU execution.",
            ],
            "Legacy official Brian2GeNN interface example for an LIF f/I curve.",
            "Retain as a minimal syntax example; use current package docs for environment setup.",
        ),
        decision(
            "ST077",
            "verified_primary",
            "https://doc.brainchipinc.com/",
            searches(
                ("BrainChip MetaTF official documentation", "https://doc.brainchipinc.com/"),
                (
                    "MetaTF installation supported versions",
                    "https://doc.brainchipinc.com/installation.html",
                ),
            ),
            [
                "The current MetaTF documentation describes akida-models, QuantizeML, CNN2SNN and the Akida runtime/software backend.",
                "The current installation page documents Python 3.10-3.12 and versioned package dependencies.",
            ],
            [
                "The runtime is a vendor stack governed by BrainChip licensing, not a wholly open-source framework.",
                "Supported Python, TensorFlow and package versions change and must be locked per experiment.",
            ],
            "Official versioned documentation for quantization, conversion, simulation and Akida deployment.",
            "Duplicate role with ST026 is retained only as documentation rather than software identity.",
        ),
        decision(
            "ST078",
            "verified_primary",
            "https://pytorch-tabular.readthedocs.io/en/latest/",
            searches(
                (
                    "PyTorch Tabular official documentation",
                    "https://pytorch-tabular.readthedocs.io/en/latest/",
                )
            ),
            [
                "The official documentation provides tutorials, API reference, model configuration, experiment tracking, cross-validation and explainability guides."
            ],
            [
                "The documentation is general-purpose and does not define participant-safe splits for pain datasets.",
                "Specific model availability is version-dependent and must be pinned.",
            ],
            "Official PyTorch Tabular documentation for structured-feature baselines.",
            "The exact documentation URL replaces the redirected source repository link.",
        ),
        rejected_requirement("ST087", "16+ CPU cores"),
        rejected_requirement("ST088", "64 GB RAM"),
        rejected_requirement("ST089", "RTX 3090/4090 with 24 GB VRAM"),
        rejected_requirement("ST090", "2 TB NVMe SSD"),
        decision(
            "ST091",
            "partially_verified",
            "https://doc.brainchipinc.com/installation.html",
            searches(
                (
                    "MetaTF supported operating systems",
                    "https://doc.brainchipinc.com/installation.html",
                )
            ),
            [
                "Current MetaTF documentation supports Windows 10/11 and manylinux-2.28-compatible Linux distributions including Ubuntu 22.04/24.04."
            ],
            [
                "This verifies one vendor dependency only, not the entire proposed simulator/ML stack.",
                "WSL2 support and the claim that this is a minimum configuration were not established.",
            ],
            "Partial compatibility note for MetaTF; full-stack OS support requires a tested lockfile and CI matrix.",
            "Remove WSL2 and minimum-system wording until end-to-end testing exists.",
        ),
        decision(
            "ST092",
            "partially_verified",
            "https://doc.brainchipinc.com/installation.html",
            searches(
                (
                    "MetaTF supported Python versions",
                    "https://doc.brainchipinc.com/installation.html",
                )
            ),
            ["Current MetaTF releases document Python 3.10-3.12 support."],
            [
                "That range does not prove compatibility of every FlyWire, simulator and ML dependency.",
                "A project Python version must be selected from a resolved dependency lock and CI results.",
            ],
            "Vendor-specific Python compatibility note, not a validated project-wide requirement.",
            "Use a tested lockfile rather than a prose version range.",
        ),
        rejected_requirement("ST093", "CUDA 12.x"),
        rejected_requirement("ST094", "32+ CPU cores / Threadripper or Xeon"),
        rejected_requirement("ST095", "128-256 GB RAM"),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
