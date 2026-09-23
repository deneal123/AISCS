"""Populate relevance-5 batches 002-008 from registry and primary-source checks."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.core import load_json  # noqa: E402
from service.pipeline import atomic_write_json  # noqa: E402

DATA = ROOT / "data"
CURATION = DATA / "curation" / "relevance-5"
CHECKED_AT = "2026-09-22"


@dataclass(frozen=True)
class Spec:
    canonical: str
    members: tuple[str, ...]
    identifier_type: str
    identifier: str | None
    title: str | None = None
    url: str | None = None
    outcome: str = "verified_metadata"
    exclusion_reason: str | None = None
    note: str = "Bibliographic metadata confirmed; full text was not used for claim extraction."


SPECS = (
    Spec(
        "S044",
        ("S057", "S081", "S117", "S126", "S145", "S263"),
        "doi",
        "10.1016/j.jpain.2026.106416",
        "External validation of EEG-based machine learning models for continuous pain prediction",
        "https://pubmed.ncbi.nlm.nih.gov/42600964/",
        "verified_primary",
        note="PubMed primary record and abstract checked; models did not beat the mean-rating dummy for continuous prediction.",
    ),
    Spec(
        "S040",
        ("S055", "S120", "S130", "S142", "S180"),
        "doi",
        "10.1016/j.inffus.2026.104173",
        "GIAFormer: A Gradient-Infused Attention and Transformer for Pain Assessment with EDA-fNIRS Fusion",
        "https://www.sciencedirect.com/science/article/pii/S1566253526000527",
        "verified_primary",
        note="Open publisher abstract checked; 65 AI4Pain subjects and LOSO accuracy 90.51% are publisher-reported.",
    ),
    Spec(
        "S079",
        ("S123", "S290", "S300", "S324", "S339"),
        "doi",
        "10.1016/j.neurom.2025.11.011",
        "Control Signals in Closed-Loop Spinal Cord Stimulation in Patients with Chronic Pain: A Scoping Review",
        "https://www.sciencedirect.com/science/article/pii/S1094715925011705",
        "verified_primary",
        note="Open publisher review checked; ECAP is a control signal, not a direct measure of pain.",
    ),
    Spec(
        "S078",
        ("S124", "S139", "S202", "S349", "S364", "S401"),
        "doi",
        "10.1016/B978-0-443-36528-7.00011-X",
        "Physiologic closed loop controlled spinal cord stimulation",
    ),
    Spec(
        "S004",
        ("S080", "S125", "S146", "S226", "S257"),
        "doi",
        "10.1109/JBHI.2026.3650972",
        "RE-HPBS-IPIC: A Resting EEG- and High-Activation Pain Brain Source-Driven Framework for Inter-Subject Pain Intensity Classification",
    ),
    Spec(
        "S082",
        ("S127", "S143", "S207", "S264", "S374"),
        "doi",
        "10.1016/j.bspc.2026.109815",
        "Pain intensity classification and evaluation of individual differences in subjects based on hybrid CNN–BiLSTM approach",
        "https://www.sciencedirect.com/science/article/pii/S1746809426003691",
        "verified_primary",
        note="Publisher abstract checked; LOSO evaluation is reported, but this does not establish clinical validity.",
    ),
    Spec(
        "S086",
        ("S129",),
        "doi",
        "10.1109/FG67764.2026.11556963",
        "Hierarchical Cross-Attention Transformer for Non-contact Multimodal Pain Classification using Remote Physiological Signals and Visual Features",
        "https://dspace.iiti.ac.in/handle/123456789/18784",
        "verified_primary",
        note="Official institutional repository metadata and abstract checked.",
    ),
    Spec(
        "S088",
        ("S119", "S131", "S179"),
        "doi",
        "10.1109/ISDA70544.2026.11606012",
        "Cross-Domain Multimodal Pain Detection Using a DANN–Transformer Architecture with Supervised Contrastive Warmup and Test-Time Augmentation",
    ),
    Spec(
        "S140",
        ("S158", "S203", "S217", "S270"),
        "patent_id",
        None,
        outcome="rejected",
        exclusion_reason="unverifiable",
        note="US20260216499 was not found in USPTO/Google Patents; no patent metadata may be cited.",
    ),
    Spec(
        "S007",
        ("S103", "S265"),
        "doi",
        "10.1109/JIOT.2026.3663683",
        "MDNet: A Lightweight Multidomain 1-D CNN for Embedded Pain Assessment Using EDA Signals",
    ),
    Spec(
        "S243",
        ("S276",),
        "patent_id",
        "NCT04662905",
        "Novel Treatment Delivery of ECAP-controlled Closed-loop SCS for Chronic Pain",
        "https://clinicaltrials.gov/study/NCT04662905",
        "partially_verified",
        note="ClinicalTrials.gov registration verified; recruiting status and estimated 2027 completion mean no outcome claim is available.",
    ),
    Spec(
        "S285",
        ("S298", "S322", "S337"),
        "doi",
        "10.1038/s44385-026-00076-8",
        "The optimization of neuroprosthetic interfaces relying on biophysical and surrogate digital twins",
    ),
    Spec(
        "S356",
        ("S358", "S403"),
        "doi",
        "10.7759/cureus.102799",
        "Impact of Evoked Compound Action Potential (ECAP)-Controlled Closed-Loop Spinal Cord Stimulation in Refractory Lumbar Radiculopathy: A Case Report",
    ),
    Spec(
        "S357",
        ("S359", "S404"),
        "doi",
        "10.21776/ub.jphv.2026.007.01.07",
        "Closing the loop on chronic pain with ECAP-controlled closed-loop vs open-loop spinal cord stimulation: systematic and longitudinal pooled analysis of the EVOKE study",
    ),
    Spec(
        "S238",
        ("S351", "S362", "S402"),
        "doi",
        "10.1007/s40122-025-00808-5",
        "Next-Generation SCS Programming Platform: Enhancing ECAP Fidelity and Objectivity to Improve Patient Experience",
    ),
    Spec(
        "S360",
        ("S408",),
        "doi",
        "10.1007/s40122-026-00821-2",
        "Objective, Same-Day SCS Trials with ECAP-Controlled Closed-Loop Therapy: Depth of Response is Maintained from Trial to 12 months",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13009343/",
        "verified_primary",
        note="Full open article checked; single-center selected cohort of 15 limits generalization.",
    ),
    Spec(
        "S361",
        ("S409",),
        "doi",
        None,
        outcome="rejected",
        exclusion_reason="unverifiable",
        note="Generic title could not be mapped uniquely to a primary publication; candidate records describe different cohorts.",
    ),
    Spec(
        "S001",
        (),
        "doi",
        "10.1038/s41928-025-01377-3",
        "Ultrasound-induced wireless implantable stimulator for adaptive pain management",
    ),
    Spec(
        "S002",
        (),
        "doi",
        "10.1088/1741-2552/adbfbe",
        "Feature extraction and prediction of spinal cord stimulation evoked compound action potentials in humans",
    ),
    Spec(
        "S003",
        ("S059",),
        "doi",
        "10.1371/journal.pone.0337726",
        "Classification of chronic pain and spinal cord stimulation response using machine learning in magnetoencephalography data",
    ),
    Spec(
        "S033",
        ("S047",),
        "doi",
        "10.1038/s41598-025-92111-8",
        "Machine learning predicts spinal cord stimulation surgery outcomes and reveals novel neural markers for chronic pain",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11920397/",
        "verified_primary",
        note="Open full article checked; this is an SCS responder study with a limited clinical cohort, not evidence for ECAP-based prediction.",
    ),
    Spec(
        "S034",
        (),
        "doi",
        "10.1227/neu.0000000000003715",
        "Prediction of Response to Spinal Cord Stimulation Using Machine Learning Based on Radiomics and Patient-Reported Outcomes",
    ),
    Spec(
        "S046",
        (),
        "doi",
        "10.1016/j.neurom.2025.08.367",
        "ID# 1907064 Explainable Machine Learning Pipeline Predicts Spinal Cord Stimulation Responders",
    ),
    Spec(
        "S006",
        ("S104",),
        "doi",
        "10.1016/j.neurom.2024.06.321",
        "ID: 318164 Using Neural Networks to Detect Evoked Compound Action Potentials Elicited with Epidural Spinal Cord Stimulation",
    ),
    Spec(
        "S236",
        ("S277",),
        "doi",
        "10.1097/BRS.0000000000005445",
        "ECAP-Controlled Closed-Loop Spinal Cord Stimulation for Chronic Nonsurgical Refractory Back Pain",
    ),
    Spec(
        "S237",
        ("S278",),
        "doi",
        "10.1136/rapm-2025-107051",
        "Clinical utility of ECAP dosing in a real-world population delivered via EVOKE therapy: the ECAP study",
    ),
    Spec(
        "S239",
        ("S275",),
        "doi",
        "10.1016/j.jpain.2024.104646",
        "Improvements in Therapy Experience With Evoked Compound Action Potential Controlled, Closed-Loop Spinal Cord Stimulation-Primary Outcome of the ECHO-MAC Randomized Clinical Trial",
        "https://pubmed.ncbi.nlm.nih.gov/39094810/",
        "verified_primary",
        note="PubMed primary abstract checked; the trial measures therapy experience and ECAP dose consistency, not ECAP as direct pain measurement.",
    ),
    Spec(
        "S289",
        ("S299", "S323", "S338"),
        "patent_id",
        "US20220323766A1",
        "Systems and methods for providing neurostimulation therapy according to machine learning operations",
        "https://patents.google.com/patent/US20220323766A1/en",
        "partially_verified",
        note="Patent identity and claims page checked; a patent is prior-art context, not empirical evidence.",
    ),
    Spec(
        "S008",
        (),
        "doi",
        "10.1088/2057-1976/ae34b4",
        "Explainable AI for pain perception: subject-independent EEG decoding using DeepSHAP and CNNs",
    ),
    Spec(
        "S014",
        (),
        "doi",
        "10.1109/TBME.2024.3452708",
        "Toward Objectification of Subjective Chronic Pain Based on Implicit Response in Biosignals",
    ),
    Spec(
        "S016",
        (),
        "doi",
        "10.3390/s25041150",
        "A Multimodal Deep Learning Approach to Intraoperative Nociception Monitoring: Integrating Electroencephalogram, Photoplethysmography, and Electrocardiogram",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11859842/",
        "verified_primary",
        note="Open full article checked; target is intraoperative nociception under anesthesia, not conscious pain.",
    ),
    Spec(
        "S037",
        ("S054", "S141", "S205"),
        "doi",
        "10.1038/s41598-025-14238-y",
        "A CrossMod-Transformer deep learning framework for multi-modal pain detection through EDA and ECG fusion",
    ),
    Spec(
        "S072",
        ("S114", "S174"),
        "doi",
        "10.1016/j.compbiomed.2025.111260",
        "AI-based bi-modal fusion system for automated clinical pain monitoring",
    ),
    Spec(
        "S011",
        (),
        "doi",
        None,
        outcome="rejected",
        exclusion_reason="unverifiable",
        note="No matching pain/SCS source was found; the exact-title Crossref hit was an unrelated crystal-growth article.",
    ),
    Spec(
        "S069",
        ("S171",),
        "doi",
        "10.1371/journal.pbio.3003948",
        "Neural encoding of pain is robust within but unstable between individuals",
    ),
    Spec(
        "S015",
        (),
        "doi",
        "10.3390/s26103020",
        "Real-Time Pain Assessment from Electrodermal Activity Using Deep Learning",
    ),
    Spec(
        "S148",
        ("S194",),
        "doi",
        "10.2147/JPR.S617733",
        "Rethinking Pain Assessment: Subjective Scales, Biomarkers, and Multimodal Integration",
    ),
    Spec(
        "S164",
        (),
        "doi",
        "10.1109/ACCESS.2026.3713429",
        "Transformer and Attention-Based Models for Automated Pain Assessment: A Systematic Review",
    ),
    Spec(
        "S195",
        (),
        "doi",
        "10.1186/s12967-026-08529-9",
        "Current state of research and future developments of artificial intelligence in pain diagnosis and treatment",
        "https://pubmed.ncbi.nlm.nih.gov/42732075/",
        "verified_primary",
        note="PubMed primary record and abstract checked; this is a review, not empirical validation.",
    ),
    Spec(
        "S005",
        ("S101",),
        "doi",
        "10.1145/3737281",
        "A Systematic Review of Multimodal Signal Fusion for Acute Pain Assessment Systems",
    ),
    Spec(
        "S070",
        ("S112", "S147", "S163", "S172"),
        "doi",
        "10.1109/MLSP62443.2025.11204206",
        "Towards Generalizable Learning Models for EEG-Based Identification of Pain Perception",
    ),
    Spec(
        "S284",
        ("S297", "S321", "S336"),
        "doi",
        "10.1093/pnasnexus/pgae488",
        "Neuromorphic neuromodulation: Towards the next generation of closed-loop neurostimulation",
    ),
)


def search_entries(
    result: dict[str, Any] | None, extra_url: str | None, title: str
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if result:
        for attempt in result.get("attempts", []):
            entries.append(
                {
                    "service": str(attempt.get("service")),
                    "query": str(attempt.get("query")),
                    "url": str(attempt.get("url")),
                    "result": "registry response saved in discovery/registry-search.json",
                }
            )
    if extra_url:
        entries.append(
            {
                "service": "primary source",
                "query": title,
                "url": extra_url,
                "result": "exact source page checked",
            }
        )
    if not entries:
        entries.append(
            {
                "service": "manual exact-title search",
                "query": title,
                "url": "https://search.crossref.org/",
                "result": "no matching primary record accepted",
            }
        )
    return entries


def candidate_for(spec: Spec, discovery: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    wanted = (spec.identifier or "").casefold()
    for source_id in (spec.canonical, *spec.members):
        for attempt in discovery.get(source_id, {}).get("attempts", []):
            for candidate in attempt.get("candidates", []):
                if str(candidate.get("doi") or candidate.get("pmid") or "").casefold() == wanted:
                    return candidate
    return None


def canonical_decision(spec: Spec, discovery: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = discovery.get(spec.canonical)
    searches = search_entries(source, spec.url, spec.title or spec.canonical)
    if spec.outcome == "rejected":
        return {
            "source_id": spec.canonical,
            "decision": "rejected",
            "checked_at": CHECKED_AT,
            "exclusion_reason": spec.exclusion_reason,
            "clear_fields": [
                "авторы",
                "издание",
                "модальность",
                "задача",
                "метод",
                "датасет",
                "производительность",
                "кросс_субъект",
            ],
            "searches": searches,
            "claims": [
                {
                    "claim": "Imported source claim is traceable to a primary record.",
                    "target_variable": "source identity",
                    "population_or_data": "not established",
                    "evidence": "No unique matching primary record was established.",
                    "limitation": spec.note,
                    "permitted_conclusion": "Do not cite as evidence.",
                }
            ],
            "notes": spec.note,
        }
    candidate = candidate_for(spec, discovery)
    title = spec.title or (candidate or {}).get("title")
    authors = "; ".join((candidate or {}).get("authors") or []) or None
    year_raw = (candidate or {}).get("year")
    try:
        year = int(year_raw) if year_raw else None
    except (TypeError, ValueError):
        year = None
    identifier_updates = {
        spec.identifier_type: spec.identifier,
        "exact_url": spec.url or (candidate or {}).get("primary_url"),
    }
    if (
        spec.identifier_type == "patent_id"
        and spec.identifier
        and spec.identifier.startswith("NCT")
    ):
        identifier_updates = {"dataset_id": spec.identifier, "exact_url": spec.url}
    updates: dict[str, Any] = {
        "название": title,
        "авторы": authors,
        "год": year,
        "издание": (candidate or {}).get("container_title"),
        "модальность": None,
        "задача": None,
        "метод": None,
        "датасет": None,
        "производительность": None,
        "кросс_субъект": None,
        "ограничения": spec.note,
        "identifiers": identifier_updates,
        "provenance": {
            "retrieved_at": CHECKED_AT,
            "search_stream": "relevance-5/registry-and-primary-review",
            "query_or_seed": title,
            "iteration": 1,
        },
        "evidence": {
            "species": None,
            "population": None,
            "subject_domain": "unknown",
            "modalities": [],
            "sample_size": None,
            "target_construct": "unknown",
            "target_label": None,
            "evidence_role": "context_only"
            if spec.outcome != "verified_primary"
            else "method_baseline",
        },
        "validation": {
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["metadata_only"] if spec.outcome == "verified_metadata" else [],
    }
    if spec.identifier_type == "patent_id":
        updates["тип_источника"] = (
            "патент" if not spec.identifier.startswith("NCT") else "применение"
        )
        updates["evidence"]["target_construct"] = (
            "not_applicable" if not spec.identifier.startswith("NCT") else "scs_response"
        )
        updates["evidence"]["evidence_role"] = (
            "context_only" if not spec.identifier.startswith("NCT") else "scs_ecap_validation"
        )
        updates["risk_flags"] = (
            ["patent_not_empirical_evidence"]
            if not spec.identifier.startswith("NCT")
            else ["metadata_only"]
        )
    return {
        "source_id": spec.canonical,
        "decision": spec.outcome,
        "checked_at": CHECKED_AT,
        "full_text_status": "checked" if spec.outcome == "verified_primary" else "metadata_only",
        "searches": searches,
        "updates": updates,
        "claims": [
            {
                "claim": "The bibliographic source exists under the verified identifier.",
                "target_variable": "source identity",
                "population_or_data": "not extracted in metadata-only decisions",
                "evidence": f"{spec.identifier_type}={spec.identifier}; exact title={title}",
                "limitation": spec.note,
                "permitted_conclusion": "Cite existence and metadata only unless full-text claim extraction is recorded.",
            }
        ],
        "notes": spec.note,
    }


def alias_decision(
    source_id: str, spec: Spec, discovery: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "decision": "alias",
        "canonical_id": spec.canonical,
        "reason": "confirmed_title_variant_of_same_primary_source",
        "checked_at": CHECKED_AT,
        "searches": search_entries(discovery.get(source_id), spec.url, spec.title or source_id),
        "claims": [],
        "notes": "The abbreviated/final/extended label does not identify a separate publication or version.",
    }


def main() -> None:
    discovery_payload = load_json(CURATION / "discovery" / "registry-search.json")
    discovery = {item["source_id"]: item for item in discovery_payload["results"]}
    by_source: dict[str, Spec] = {}
    for spec in SPECS:
        for source_id in (spec.canonical, *spec.members):
            if source_id in by_source:
                raise RuntimeError(f"source appears in multiple specs: {source_id}")
            by_source[source_id] = spec

    for batch_number in range(2, 9):
        path = CURATION / "batches" / f"batch-{batch_number:03d}.json"
        payload = load_json(path)
        missing = [source_id for source_id in payload["source_ids"] if source_id not in by_source]
        if missing:
            raise RuntimeError(f"batch {batch_number} lacks specs: {missing}")
        decisions = []
        for source_id in payload["source_ids"]:
            spec = by_source[source_id]
            decisions.append(
                canonical_decision(spec, discovery)
                if source_id == spec.canonical
                else alias_decision(source_id, spec, discovery)
            )
        payload["decisions"] = decisions
        payload["meta"]["status"] = "reviewed"
        payload["meta"]["reviewed_at"] = CHECKED_AT
        atomic_write_json(path, payload)


if __name__ == "__main__":
    main()
