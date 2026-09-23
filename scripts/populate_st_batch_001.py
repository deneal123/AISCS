"""Populate the first ST review batch from checked primary project pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-001.json"
TODAY = date.today().isoformat()


def search(query: str, url: str) -> list[dict[str, str]]:
    return [{"query": query, "url": url, "accessed_at": TODAY}]


def decision(
    resource_id: str,
    outcome: str,
    url: str,
    query: str,
    claims: list[str],
    limitations: list[str],
    purpose: str,
    note: str,
) -> dict:
    return {
        "resource_id": resource_id,
        "decision": outcome,
        "exact_url": url,
        "checked_at": TODAY,
        "searches": search(query, url),
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
            "ST002",
            "verified_primary",
            "https://github.com/seung-lab/FlyConnectome",
            "seung-lab FlyConnectome programmatic access CAVE tutorial",
            [
                "Repository contains CAVE and mesh-access notebooks for FlyWire.",
                "README identifies Codex as the bulk-download source.",
            ],
            ["Data-access tutorials only; this is not a neural or embodied simulator."],
            "Tutorials for programmatic FlyWire access through CAVE, meshes and Codex exports.",
            "Repository content checked; simulation capability is not claimed.",
        ),
        decision(
            "ST003",
            "verified_primary",
            "https://github.com/murthylab/flywire-network-analysis",
            "murthylab flywire network analysis v630",
            [
                "Repository contains scripts for network analyses of the FlyWire connectome.",
                "README links the associated network and data preprints.",
            ],
            ["The published scripts describe the v630 snapshot, not current v783 data."],
            "Network-analysis scripts and derived products for the FlyWire v630 snapshot.",
            "Retained as analysis prior art; version mismatch must be explicit.",
        ),
        decision(
            "ST004",
            "partially_verified",
            "https://github.com/YijieYin/connectome_data_prep",
            "YijieYin connectome_data_prep FlyWire FAFB MaleCNS",
            ["Repository exists and contains FAFB, maleCNS and other preparation workflows."],
            [
                "The repository landing page does not confirm the imported claim about a tinyurl v783 interface.",
                "Individual notebooks and their data-version assumptions still require execution-level review.",
            ],
            "Research repository with preparation notebooks for FAFB, MaleCNS and related connectome data.",
            "Specific v783 convenience-interface claim was removed as unconfirmed.",
        ),
        decision(
            "ST007",
            "verified_primary",
            "https://github.com/eonsystemspbc/fly-brain",
            "eonsystemspbc fly-brain Brian2CUDA PyTorch NEST GPU GeNN",
            [
                "Repository provides Brian2, Brian2CUDA, PyTorch, NEST GPU, GeNN and Brian2GeNN backends.",
                "README documents FlyWire v783 input files and reproducible benchmark commands.",
            ],
            [
                "This is a connectome-constrained LIF benchmark, not an embodied nociception model.",
                "Repository-reported benchmark results were not independently rerun in this audit.",
            ],
            "FlyWire v783 LIF benchmark implementation across six simulation backends.",
            "Suitable simulator candidate only after local reproducibility and biological-scope checks.",
        ),
        decision(
            "ST008",
            "partially_verified",
            "https://github.com/legacyindiesubmissions-ai/claude-fly",
            "legacyindiesubmissions-ai claude-fly embodied Drosophila simulation",
            [
                "Repository and accompanying 2026 Zenodo preprint are linked from the README.",
                "README describes a FlyWire-derived spiking network coupled to NeuroMechFly/MuJoCo.",
            ],
            [
                "Scientific and behavioral claims are self-reported and not independently validated here.",
                "The README clone command points to a differently named repository.",
                "Claims of primacy and low-cost hardware are not evidence of biological fidelity.",
            ],
            "Experimental repository claiming FlyWire-derived spiking activity coupled to a simulated body.",
            "Do not cite as a validated whole-brain emulation or nociception model.",
        ),
        decision(
            "ST009",
            "verified_primary",
            "https://github.com/snedea/flybrain",
            "snedea flybrain 139255 LIF Web Worker",
            [
                "README states 139,255 LIF neurons and 2.7M connections from FlyWire FAFB v783.",
                "The implementation runs in a browser Web Worker and exposes interactive stimuli.",
            ],
            [
                "Behavior-emergence statements are repository claims, not peer-reviewed validation.",
                "The connection reduction from the source connectome requires methodological review.",
            ],
            "Interactive browser LIF visualization derived from a reduced FlyWire v783 graph.",
            "Candidate for software comparison, not direct biological ground truth.",
        ),
        decision(
            "ST011",
            "verified_primary",
            "https://github.com/artem-x-meta/fly-arena",
            "artem-x-meta fly-arena MaleCNS FlyGym MuJoCo",
            [
                "Repository combines MaleCNS data, a NeuroMechFly body and explicit controllers.",
                "README documents local preparation, checksums and diagnostic/ablation controls.",
            ],
            [
                "The authors explicitly describe it as experimental and not physiologically validated.",
                "Several displayed behaviors are engineered controllers and can run with the connectome disabled.",
            ],
            "Experimental MaleCNS/FlyGym environment with explicit hybrid behavioral controllers.",
            "Useful integration scaffold; engineered behavior must not be attributed to the connectome.",
        ),
        decision(
            "ST012",
            "verified_primary",
            "https://github.com/MakazhanAlpamys/soup-connectome",
            "MakazhanAlpamys soup-connectome MaleCNS benchmark",
            [
                "Repository implements resident and streamed sparse-graph runtimes for MaleCNS data.",
                "README labels measured, estimated and not-tested evidence separately.",
            ],
            [
                "No biological calibration or scientific fidelity claim is made.",
                "Reported timings are host-specific infrastructure measurements.",
            ],
            "Infrastructure benchmark for resident and streamed execution of a MaleCNS-derived sparse graph.",
            "Retain for runtime engineering only, not as neuroscience validation.",
        ),
        decision(
            "ST013",
            "verified_primary",
            "https://github.com/chaobrain/fitting_drosophila_whole_brain_spiking_model",
            "chaobrain fitting Drosophila whole brain spiking model",
            [
                "Repository implements a two-stage SNN plus RNN activity-fitting workflow.",
                "README identifies FlyWire 630/783 and Drosophila neural recordings as inputs.",
                "README links the associated Nature Communications article DOI 10.1038/s41467-026-68453-w.",
            ],
            [
                "The local workflow was not executed in this audit.",
                "Activity fitting does not establish nociception, pain or embodied behavior validity.",
            ],
            "Two-stage SNN/RNN workflow for fitting region-level Drosophila neural dynamics.",
            "Promising simulation candidate subject to local reproduction and task-specific validation.",
        ),
        decision(
            "ST014",
            "partially_verified",
            "https://jesmjones.github.io/projects/01-circuits/",
            "Jessica Jones Circuit Reconstruction Drosophila nociception",
            [
                "Author project page describes circuit reconstruction, optogenetics and behavior analysis for adult-fly nociception.",
                "The page links preprint DOI 10.1101/2025.10.28.684868 and its analysis-code repository.",
            ],
            [
                "The imported md-neuron to two-pathway summary was not verified from the project page alone.",
                "The linked work is a preprint and must not be treated as settled evidence of subjective pain.",
            ],
            "Primary project page and preprint/code links for adult Drosophila nociceptive circuit reconstruction.",
            "Use only for nociceptive pathways and defensive behavior, not subjective pain.",
        ),
        decision(
            "ST016",
            "verified_primary",
            "https://male-cns.janelia.org/download/",
            "Janelia MaleCNS v1.0 download 166700 neurons",
            [
                "Official project provides MaleCNS v1.0 annotations, connectivity, skeletons and neuPrint access.",
                "Official project reports 166,700 neurons across brain and ventral nerve cord.",
                "Dataset is licensed CC BY.",
            ],
            [
                "MaleCNS and female FAFB/FlyWire are different specimens and scopes.",
                "The original 25.5M-connections wording was removed because the official download exposes multiple count definitions.",
            ],
            "Official MaleCNS v1.0 download and programmatic-access page for the complete male CNS connectome.",
            "Use explicit release, filtering and count definitions in every derived dataset.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
