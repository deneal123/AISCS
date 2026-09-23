"""Populate the final proposed hardware and aggregate-stack ST batch."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-007.json"
TODAY = date.today().isoformat()


def decision(
    resource_id: str,
    outcome: str,
    exact_url: str | None,
    searches: list[dict[str, str]],
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
        "searches": searches,
        "verified_claims": claims,
        "limitations": limitations,
        "corrected_purpose": purpose,
        "note": note,
    }


def rejected(resource_id: str, label: str, reason: str) -> dict:
    reference_urls = {
        "ST096": "https://github.com/brian-team/brian2genn",
        "ST097": "https://github.com/seung-lab/FlyConnectome",
        "ST099": "https://github.com/brian-team/brian2",
        "ST100": "https://github.com/Lightning-AI/lightning",
        "ST101": "https://github.com/SCORE-Lab-SMM-SCS/ScsInSCIMechanisms",
        "ST102": "https://docs.edgeimpulse.com/hardware/boards/brainchip-akd1000",
        "ST103": "https://www.nit.ovgu.de/BioVid.html",
        "ST104": "https://research.google.com/colaboratory/faq.html",
    }
    reference_url = reference_urls[resource_id]
    return decision(
        resource_id,
        "rejected",
        None,
        [
            {
                "query": f"primary documentation supporting {label}",
                "url": reference_url,
                "accessed_at": TODAY,
            }
        ],
        [],
        [reason],
        f"Non-evidentiary planning item: {label}.",
        "Rejected from the source registry; preserve actionable choices in versioned environment or experiment specifications instead.",
    )


def main() -> None:
    payload = load_json(PATH)
    payload["meta"].update({"status": "reviewed", "reviewed_at": TODAY})
    payload["decisions"] = [
        rejected(
            "ST096",
            "recommended GPU",
            "The proposed 2x A100 80 GB or 4x RTX 4090 configuration has no measured target workload, scaling curve or cost justification.",
        ),
        rejected(
            "ST097",
            "recommended storage",
            "The proposed 4 TB NVMe plus 8 TB HDD capacity has no dataset inventory, retention policy or generated-data volume model.",
        ),
        decision(
            "ST098",
            "partially_verified",
            "https://brainchip.com/press/brainchip-launches-akd1500-pcie-card-for-edge-ai-evaluation-everywhere/",
            [
                {
                    "query": "BrainChip AKD1500 official evaluation hardware",
                    "url": "https://brainchip.com/press/brainchip-launches-akd1500-pcie-card-for-edge-ai-evaluation-everywhere/",
                    "accessed_at": TODAY,
                }
            ],
            [
                "BrainChip offers AKD1500 evaluation hardware and an associated vendor software stack for edge-AI evaluation."
            ],
            [
                "No experiment currently requires Akida hardware and no project model has been converted or benchmarked on it.",
                "Calling the hardware recommended is unsupported until it beats software baselines on a predefined edge-deployment metric.",
            ],
            "Optional edge-deployment candidate behind a later measured go/no-go gate.",
            "Hardware existence is confirmed; procurement recommendation is not.",
        ),
        rejected(
            "ST099",
            "simulation stack list",
            "This is an aggregate architecture proposal, not a source; several listed tools were separately validated and NEST GPU was not established as a chosen dependency.",
        ),
        rejected(
            "ST100",
            "ML stack list",
            "This is an unversioned aggregate dependency list, not evidence; packages must be selected per baseline and pinned in a lockfile.",
        ),
        rejected(
            "ST101",
            "SCS modeling stack list",
            "This is an aggregate planning list and does not demonstrate compatibility, shared outputs or an ECAP measurement model.",
        ),
        rejected(
            "ST102",
            "neuromorphic hardware stack list",
            "This duplicates separately curated BrainChip and Edge Impulse resources and provides no benchmark or decision criterion.",
        ),
        rejected(
            "ST103",
            "human-data stack list",
            "This mixes datasets with different targets, modalities, access conditions and licenses; each dataset must remain a separately validated source card.",
        ),
        rejected(
            "ST104",
            "cloud stack list",
            "This duplicates the Google Colab resource and its unguaranteed accelerator availability; it is not an independent source.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
