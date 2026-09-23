"""Populate the first relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-001.json"
TODAY = date.today().isoformat()


def search(query: str, url: str) -> list[dict[str, str]]:
    return [{"query": query, "url": url, "accessed_at": TODAY}]


def canonical(
    source_id: str,
    outcome: str,
    title: str,
    url: str,
    *,
    doi: str | None = None,
    patent_id: str | None = None,
    authors: str | None = None,
    source: str | None = None,
    note: str,
    target: str = "not_applicable",
    role: str = "context_only",
    risks: list[str] | None = None,
    claim: str = "The source identity and bibliographic record were confirmed.",
) -> dict[str, Any]:
    identifiers = {
        "doi": doi,
        "pmid": None,
        "arxiv_id": None,
        "patent_id": patent_id,
        "dataset_id": None,
        "exact_url": url,
    }
    updates: dict[str, Any] = {
        "название": title,
        "identifiers": identifiers,
        "evidence": {"target_construct": target, "evidence_role": role},
        "risk_flags": risks or [],
    }
    if authors:
        updates["авторы"] = authors
    if source:
        updates["издание"] = source
    return {
        "source_id": source_id,
        "decision": outcome,
        "checked_at": TODAY,
        "full_text_status": "checked" if outcome == "verified_primary" else "metadata_only",
        "searches": search(title, url),
        "updates": updates,
        "claims": [
            {
                "claim": claim,
                "target_variable": target,
                "population_or_data": "as described by the primary source",
                "evidence": f"Stable source: {doi or patent_id or url}",
                "limitation": note,
                "permitted_conclusion": "Use only within the documented scope and limitations.",
            }
        ],
        "notes": note,
    }


def rejected(source_id: str, title: str, query_url: str, note: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "decision": "rejected",
        "checked_at": TODAY,
        "exclusion_reason": "unverifiable",
        "searches": search(title, query_url),
        "updates": {"risk_flags": ["claim_not_supported"]},
        "claims": [],
        "notes": note,
    }


def alias(source_id: str, canonical_id: str, title: str, url: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "decision": "alias",
        "canonical_id": canonical_id,
        "reason": "confirmed_title_variant_of_same_primary_source",
        "checked_at": TODAY,
        "searches": search(title, url),
        "claims": [],
        "notes": "The final/extended/abbreviated label does not identify a separate source version.",
    }


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S065": canonical(
            "S065",
            "verified_primary",
            "Dopaminergic Modulation of Mushroom Body Output Neurons Mediates Nociception-Induced Escape in Drosophila",
            "https://elifesciences.org/reviewed-preprints/110557",
            doi="10.7554/eLife.110557.1",
            authors="Chi-Lien Yang; Chia-Wen Chen; Kuan-Lin Feng; Hsiao-Chien Peng; Ming-Chin Wu; Ching-Che Charng; Li-An Chu; Yeong-Ray Wen; Ann-Shyn Chiang",
            source="eLife reviewed preprint",
            note="Reviewed preprint v1; anatomical tracing and perturbation support nociception-induced escape circuitry, not subjective pain or human transfer.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["preprint", "animal_to_human_transfer_unvalidated"],
            claim="The reviewed preprint reports dopaminergic mushroom-body modulation of nociception-induced escape in adult Drosophila.",
        ),
        "S170": alias(
            "S170",
            "S065",
            "Dopaminergic modulation extended",
            "https://elifesciences.org/reviewed-preprints/110557",
        ),
        "S198": alias(
            "S198",
            "S065",
            "Dopaminergic modulation final",
            "https://elifesciences.org/reviewed-preprints/110557",
        ),
        "S138": canonical(
            "S138",
            "verified_primary",
            "Drosophila emulations are intrinsically affectively indeterminate",
            "https://doi.org/10.56280/1765455593",
            doi="10.56280/1765455593",
            authors="Marek Dobeš",
            source="Journal of Multiscale Neuroscience",
            note="Perspective article proposing an audit framework; it explicitly concludes present affective indeterminacy rather than evidence of suffering or harmlessness.",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The perspective argues that current Drosophila emulations do not establish a determinate affective state.",
        ),
        "S199": alias(
            "S199", "S138", "Affective indeterminacy final", "https://doi.org/10.56280/1765455593"
        ),
        "S232": alias(
            "S232",
            "S138",
            "Affective indeterminacy extended",
            "https://doi.org/10.56280/1765455593",
        ),
        "S144": canonical(
            "S144",
            "verified_metadata",
            "Method and apparatus for adaptive neural interfaces",
            "https://patents.google.com/patent/WO2026146221A1/en",
            patent_id="WO2026146221A1",
            authors="ONWARD MEDICAL NV",
            source="WIPO patent publication",
            note="Patent identity and abstract-level metadata confirmed; claimed federated predictive analysis is prior art, not empirical efficacy evidence.",
            risks=["patent_not_empirical_evidence", "metadata_only"],
            claim="WO2026146221A1 describes federated predictive analysis across neural-interface users and devices.",
        ),
        "S204": alias(
            "S204",
            "S144",
            "WO2026146221A1 final",
            "https://patents.google.com/patent/WO2026146221A1/en",
        ),
        "S215": alias(
            "S215",
            "S144",
            "WO2026146221A1 extended",
            "https://patents.google.com/patent/WO2026146221A1/en",
        ),
        "S271": alias(
            "S271",
            "S144",
            "WO2026146221A1 final",
            "https://patents.google.com/patent/WO2026146221A1/en",
        ),
        "S150": rejected(
            "S150",
            "Real-time gait phase detection with federated learning",
            "https://scholar.google.com/scholar?q=%22Real-time+gait+phase+detection%22+%22federated+learning%22",
            "No exact primary source matching the imported federated-learning title was found; nearby gait-phase papers use other methods.",
        ),
        "S216": alias(
            "S216",
            "S150",
            "Real-time gait phase detection extended",
            "https://scholar.google.com/scholar?q=%22Real-time+gait+phase+detection%22+%22federated+learning%22",
        ),
        "S316": alias(
            "S316",
            "S150",
            "Real-time gait phase detection extended",
            "https://scholar.google.com/scholar?q=%22Real-time+gait+phase+detection%22+%22federated+learning%22",
        ),
        "S231": canonical(
            "S231",
            "verified_primary",
            "Neuromorphic Technologies for Neuroengineering: From Adaptive Stimulation to SNN-Based Inference and Deployable Biointerfaces",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC13210900/",
            source="Open-access review indexed in PubMed Central",
            note="Broad review and context source; it does not demonstrate clinical superiority of neuromorphic systems or validate the dissertation transfer hypothesis.",
            risks=[],
            claim="The review surveys neuromorphic stimulation, biosignal inference and wearable or implantable biointerfaces while emphasizing translational evidence gaps.",
        ),
        "S248": alias(
            "S248",
            "S231",
            "Neuromorphic technologies extended",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC13210900/",
        ),
        "S167": rejected(
            "S167",
            "Circuit Reconstruction of nociceptive circuits (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Circuit+Reconstruction%22+nociceptive+Drosophila+Jones",
            "The vague title and author could not be mapped uniquely to a 2026 primary source; established older circuit papers are not the same record.",
        ),
        "S200": canonical(
            "S200",
            "verified_primary",
            "DoomFly: fly-connectome simulation controlling a Doom arena",
            "https://github.com/nftechie/doomfly",
            authors="Alex Wormuth",
            source="GitHub software repository",
            note="Public implementation with explicit failed visual, conditioning and survival gates; engineered damage input is not natural nociception or pain.",
            target="not_applicable",
            role="simulation_foundation",
            risks=["synthetic_only", "animal_to_human_transfer_unvalidated"],
            claim="The repository connects a MaleCNS-derived simulation to engineered ViZDoom inputs and controls but does not demonstrate learned survival.",
        ),
        "S212": canonical(
            "S212",
            "verified_primary",
            "Combining brain-wide activity imaging with electron microscopy reveals a distributed nociceptive network in the brain",
            "https://doi.org/10.1101/2025.09.25.678485",
            doi="10.1101/2025.09.25.678485",
            authors="N. Randel; C. Wang; M. S. Clayton; K. Wang; S. Pang; S. C. Xu; A. Champion; H. F. Hess; A. Cardona; P. J. Keller; M. Zlatic",
            source="bioRxiv",
            note="Preprint maps larval Drosophila nociceptive activity to EM anatomy; it is not a whole-brain simulator or evidence of subjective pain.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["preprint", "animal_to_human_transfer_unvalidated"],
            claim="The preprint combines whole-brain activity imaging and subsequent EM in the same larval brain to identify a distributed nociceptive network.",
        ),
        "S272": canonical(
            "S272",
            "verified_metadata",
            "CN122075919A",
            "https://patents.google.com/patent/CN122075919A/en",
            patent_id="CN122075919A",
            note="Patent publication identifier retained at metadata level; technical claims and relevance require translation and claims review.",
            risks=["patent_not_empirical_evidence", "metadata_only"],
        ),
        "S273": canonical(
            "S273",
            "verified_primary",
            "MenstruEase: A Closed-Loop Smart TENS System for Personalized Management of Primary Dysmenorrhea",
            "https://doi.org/10.1002/adsu.70449",
            doi="10.1002/adsu.70449",
            authors="Sixun Chen; Sukhera Ahmad Yar; Sabrina Han; Peiran Wang; Wenqing Xiong; Xingyi Yang; Boyuan Gao; Farah Deeba; Xingyi Ma",
            source="Advanced Sustainable Systems",
            note="Proof-of-concept efficacy is from a mouse hot-plate experiment; AI pain detection is a roadmap, not a validated human clinical result.",
            target="nociceptive_response",
            role="context_only",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The article describes a multimodal closed-loop TENS prototype and reports only animal proof-of-concept efficacy.",
        ),
        "S279": canonical(
            "S279",
            "verified_primary",
            "Principles of Physiologic Closed-Loop Controllers in Neuromodulation",
            "https://pubmed.ncbi.nlm.nih.gov/42059841/",
            doi="10.1016/j.neurom.2026.03.010",
            authors="Victoria S. Marks et al.",
            source="Neuromodulation",
            note="Framework/guidance article; its SCS case study treats ECAP as a reactive biomarker of spinal activation, not a direct pain measure or outcome predictor.",
            target="ecap_neural_recruitment",
            role="scs_ecap_validation",
            risks=["ecap_not_pain_measure"],
            claim="The article classifies ECAP as a reactive biomarker for spinal activation in a physiologic closed-loop SCS example.",
        ),
        "S313": rejected(
            "S313",
            "Agentic AI in Neurology",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Agentic+AI+in+Neurology%22",
            "No uniquely identifiable primary publication with this exact generic title was found.",
        ),
        "S327": alias(
            "S327",
            "S313",
            "Agentic AI in Neurology extended",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Agentic+AI+in+Neurology%22",
        ),
        "S342": alias(
            "S342",
            "S313",
            "Agentic AI in Neurology final",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Agentic+AI+in+Neurology%22",
        ),
        "S320": canonical(
            "S320",
            "partially_verified",
            "Emergent Individuality and Neural Integration in Whole-Brain Connectome Simulations of Drosophila melanogaster",
            "https://doi.org/10.5281/zenodo.19152238",
            doi="10.5281/zenodo.19152238",
            authors="Enrique Manuel Rojas Aliaga",
            source="Zenodo preprint and public code repository",
            note="Identity and public artifacts are confirmed, but strong whole-brain behavior and individuality metrics are author-reported and not independently reproduced.",
            role="simulation_foundation",
            risks=["preprint", "synthetic_only", "animal_to_human_transfer_unvalidated"],
            claim="The preprint and repository report an embodied FlyWire-based simulation with plasticity and divergent synthetic trajectories.",
        ),
    }
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
