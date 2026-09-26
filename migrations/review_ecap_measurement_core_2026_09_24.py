"""Resolve the core ECAP/SCS measurement cards and publish a dimension audit."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from migrations.review_ecap_scs_batch_2026_09_24 import (
    CROSS_SUBJECT,
    DATASET,
    LIMITATIONS,
    METHOD,
    MODALITY,
    PERFORMANCE,
    TASK,
    _update_record,
)
from service.completeness import completeness_summary
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
BATCH_ID = "ecap-measurement-core-2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S105": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/40073452/",
        "fields": {
            MODALITY: "Epidural SCS ECAP waveforms recorded through two externalized percutaneous leads",
            TASK: "Classify individual pulses as ECAP, non-ECAP or artifact and model waveform features across stimulation settings",
            METHOD: "Artifact cleaning, PCA clustering, K-nearest-neighbor classification and generalized linear mixed-effects models",
            DATASET: "Eight chronic-pain participants undergoing an externalized SCS trial; two caudal contacts stimulated and remaining contacts recorded",
            PERFORMANCE: "AUC separated ECAP from non-ECAP better than peak-to-peak amplitude (d'=2.44 versus 2.27); preferred polarities reduced current by about 1.25 mA",
            CROSS_SUBJECT: "no: participant variability was modeled, but no held-out-participant validation is reported",
            LIMITATIONS: "Small eight-participant observational trial. Pulse-level classification and mixed-effects modeling do not establish participant-independent prediction. ECAP is a neural-response/control signal, not a direct measurement of pain or clinical response.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Eight participants with chronic pain during an externalized SCS trial",
            "subject_domain": "human_clinical",
            "modalities": ["ecap"],
            "sample_size": 8,
            "target_construct": "ecap_neural_recruitment",
            "target_label": "Individual-pulse ECAP, non-ECAP or artifact class and waveform features",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "recording", "cross_subject": "no", "external_validation": "no", "calibration": "not_reported", "uncertainty": "not_reported"},
        "risk_flags": ["ecap_not_pain_measure", "missing_cross_subject_validation"],
        "locator": "PubMed abstract, Approach and Main results; PMID 40073452; trial NCT04938245",
        "claim": "An eight-participant study explicitly links contact geometry and pulse parameters to individual ECAP features.",
        "verified": "The primary abstract reports the sample, two-lead geometry, stimulating/recording contacts, varied amplitude/pulse width/polarity and discrimination statistics.",
        "permitted": "Use as human ECAP feature-extraction and parameter-dependence evidence, not as pain measurement or cross-participant validation.",
    },
    "S159": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41605141/",
        "pmid": "41605141",
        "fields": {
            MODALITY: "Longitudinal human SCS ECAP recordings with stimulation artifact",
            TASK: "Remove biphasic stimulation artifact without distorting ECAP neural-response morphology",
            METHOD: "Biphasic electrostimulation artifact model based on additivity and boundary conditions; bilinear growth-curve E-score evaluation",
            DATASET: "Two SCS patients; nine months of therapy, 208,336 retained signals across 900 stimulation settings",
            PERFORMANCE: "BEAM achieved the highest E-scores among compared methods and reduced stimulation artifacts without distorting neural-activity information; exact effect sizes require the full tables",
            CROSS_SUBJECT: "no: two-patient longitudinal technical validation without held-out-patient evaluation",
            LIMITATIONS: "Only two patients and no independent cohort. The method validates artifact extraction across recorded stimulation settings; it does not validate pain intensity, analgesic response or participant-independent performance.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Two SCS patients with nine months of longitudinal clinical recordings",
            "subject_domain": "human_clinical",
            "modalities": ["ecap"],
            "sample_size": "2 patients; 208336 retained signals under 900 stimulation settings",
            "target_construct": "technical_signal_quality",
            "target_label": "Stimulation-artifact suppression and preserved ECAP morphology",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "recording", "cross_subject": "no", "external_validation": "no", "calibration": "not_reported", "uncertainty": "not_reported"},
        "risk_flags": ["ecap_not_pain_measure", "future_or_recent_record_requires_recheck", "missing_cross_subject_validation"],
        "locator": "PubMed PMID 41605141, abstract; IEEE full text, Methods and Results tables",
        "claim": "BEAM is a human-recording artifact model evaluated on longitudinal SCS ECAP data.",
        "verified": "The primary abstract confirms the artifact model, growth-curve E-score and validation on nine months of clinical recordings.",
        "permitted": "Use as artifact-removal prior art; do not treat the E-score as pain, recruitment accuracy or clinical-response evidence.",
    },
    "S162": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13009299/",
        "pmid": "41505067",
        "fields": {
            MODALITY: "ECAP activation plots, stimulation configurations, artifact leakage, signal-to-noise ratio and user questionnaires",
            TASK: "Automated selection and programming of ECAP dose-controlled closed-loop SCS configurations",
            METHOD: "Assisted Programming Module tests four to eight anode/cathode and pulse-width candidates while evaluating multiple sensing configurations; corrected artifact-model filtering",
            DATASET: "Freshwater NCT04662905 (34 initial sessions) and Rosella NCT06057480 (50 initial sessions); 84 sessions total",
            PERFORMANCE: "81/84 automated programs succeeded; median programming time 11.9 min; mean SNR 4.6±1.2; 35% SNR improvement and 75% lower detectable artifact leakage",
            CROSS_SUBJECT: "not_applicable: two prospective multicenter single-arm feasibility studies, not a prediction generalization study",
            LIMITATIONS: "Single-arm feasibility studies. Freshwater outcomes are in-clinic, objective neural metrics are limited to Rosella, and neither study collected baseline pain characteristics or therapy-efficacy outcomes. A 2026 correction changed the named comparator filter to the Artefact Model Method.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Adults with chronic intractable trunk and/or limb pain in two multicenter feasibility studies",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": "84 initial programming sessions (Freshwater 34; Rosella 50)",
            "target_construct": "technical_signal_quality",
            "target_label": "Successful program generation, ECAP signal fidelity and programming acceptability",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "participant", "cross_subject": "not_applicable", "external_validation": "no", "calibration": "yes", "uncertainty": "yes"},
        "risk_flags": ["ecap_not_pain_measure", "future_or_recent_record_requires_recheck"],
        "locator": "PMC13009299, Methods: Study Population and APM Platform; Results; Limitations; correction DOI 10.1007/s40122-026-00838-7",
        "claim": "Two feasibility studies quantify automated ECAP-program generation and signal-fidelity performance.",
        "verified": "The corrected open full text provides cohorts, configuration workflow, stimulation ramps, recording configurations, SNR and artifact-leakage metrics.",
        "permitted": "Use as programming and signal-quality evidence only; the study did not collect therapy-efficacy outcomes.",
    },
    "S239": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/39094810/",
        "pmid": "39094810",
        "fields": {
            MODALITY: "ECAP amplitude, stimulation dose consistency, Likert therapy-experience ratings and patient preference",
            TASK: "Compare ECAP-controlled closed-loop with open-loop SCS during activities of daily living",
            METHOD: "Prospective multicenter randomized single-blind crossover trial (ECHO-MAC, NCT04765735)",
            DATASET: "42 chronic-pain participants in the intent-to-treat analysis",
            PERFORMANCE: "97.6% had reduced sensation with closed-loop SCS; lower confidence limit 87.4% exceeded the 50% goal; 37/42 preferred closed loop; ECAP-amplitude SD 8.72 µV versus 19.95 µV",
            CROSS_SUBJECT: "not_applicable: participant-level randomized crossover clinical comparison, not a prediction model",
            LIMITATIONS: "The primary endpoint is therapy sensation/experience and dose consistency, not analgesic efficacy or future-response prediction. ECAP amplitude is used as a neural activation control signal and must not be interpreted as pain intensity.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "42 participants with chronic trunk and/or limb pain in the ECHO-MAC intent-to-treat set",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": 42,
            "target_construct": "clinical_function",
            "target_label": "Overstimulation sensation during daily activities, therapy preference and ECAP-dose variability",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "participant", "cross_subject": "not_applicable", "external_validation": "no", "calibration": "not_reported", "uncertainty": "yes"},
        "risk_flags": ["ecap_not_pain_measure"],
        "locator": "PubMed PMID 39094810, abstract; ClinicalTrials.gov NCT04765735 protocol",
        "claim": "ECHO-MAC compares closed-loop and open-loop SCS for therapy experience and ECAP-dose consistency.",
        "verified": "The primary abstract confirms randomized crossover design, 42-person ITT cohort, endpoint, preference and ECAP-amplitude variability.",
        "permitted": "Use as closed-loop dose-consistency and therapy-experience evidence, not as direct pain measurement or responder prediction.",
    },
    "S279": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/42059841/",
        "pmid": "42059841",
        "fields": {
            MODALITY: "Generic physiologic feedback and feedforward biomarkers, including ECAP in an SCS example",
            TASK: "Standardize physiologic closed-loop controller terminology, risk management and development lifecycle",
            METHOD: "Framework/guidance synthesis aligned with 2023 FDA technical considerations and control-systems theory",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_applicable: non-empirical framework article",
            LIMITATIONS: "Guidance/framework article with three exemplary technologies, not an empirical ECAP cohort. It supports terminology and controller-risk analysis only and does not validate signal accuracy, pain assessment or clinical benefit.",
        },
        "evidence": {
            "species": "not_applicable",
            "population": "Non-empirical framework with three exemplary neuromodulation technologies",
            "subject_domain": "mixed",
            "modalities": ["ecap", "other"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Reactive/feedforward biomarker classification and closed-loop controller risk framework",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "not_applicable", "cross_subject": "not_applicable", "external_validation": "not_applicable", "calibration": "not_applicable", "uncertainty": "not_applicable"},
        "risk_flags": ["ecap_not_pain_measure", "future_or_recent_record_requires_recheck"],
        "locator": "PubMed PMID 42059841, Rationale and Results/Conclusions abstract sections",
        "claim": "The framework distinguishes reactive and predictive biomarkers within physiologic closed-loop controllers.",
        "verified": "The primary abstract confirms the controller taxonomy, FDA-aligned risk-management framing and three illustrative technologies.",
        "permitted": "Use for controller terminology and risk analysis only, not as empirical ECAP or SCS outcome evidence.",
    },
    "S360": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13009343/",
        "pmid": "41774424",
        "fields": {
            MODALITY: "ECAP neural-dose telemetry, percentage pain relief, VAS, Pain Impact Score and functional outcomes",
            TASK: "Assess whether selected same-day ECAP-controlled SCS trial responders maintain outcomes through 12 months",
            METHOD: "Single-center selected subgroup from prospective multicenter ECAP Study NCT04319887; paired longitudinal analyses",
            DATASET: "15 day-0 responders; 13 proceeded to permanent implantation and 11 completed 12-month follow-up",
            PERFORMANCE: "Mean pain reduction 85.5% at day 0 and 79.6% at 12 months; responder rate 81.8-92.3%; 57.1-72.7% improved in at least four health domains",
            CROSS_SUBJECT: "not_applicable: selected longitudinal clinical cohort, not a predictive model",
            LIMITATIONS: "Small single-center, nonrandomized, responder-selected cohort using one system; insurance eligibility and 100% day-0 success create selection bias. The design cannot establish generalizable prediction or separate ECAP control from treatment/context effects.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Fifteen selected day-0 responders with chronic intractable trunk and/or limb pain",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": "15 enrolled in this analysis; 13 implanted; 11 with complete 12-month follow-up",
            "target_construct": "scs_response",
            "target_label": "Pain reduction and multidomain outcomes at day 0, 3 months and 12 months",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "participant", "cross_subject": "not_applicable", "external_validation": "no", "calibration": "yes", "uncertainty": "yes"},
        "risk_flags": ["ecap_not_pain_measure", "claim_not_supported", "future_or_recent_record_requires_recheck"],
        "locator": "PMC13009343, Abstract; Methods: Participants and neural metrics; Statistical Analysis; Limitations",
        "claim": "A selected 15-person same-day trial subgroup was followed with separate clinical outcomes and ECAP neural-dose metrics.",
        "verified": "The full text provides cohort flow, two 12-contact lead geometry, longitudinal endpoints, neural metrics, analyses and limitations.",
        "permitted": "Use as selected-cohort feasibility evidence; do not call it external prediction validation or equate ECAP dose with pain relief.",
    },
    "S363": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/40767809/",
        "pmid": "40767809",
        "fields": {
            MODALITY: "Swine anatomical imaging, epidural spinal recordings and simulated ECAP waveforms",
            TASK: "Explain dependence of recorded ECAP morphology on anatomy, lead position, waveform and stimulation configuration",
            METHOD: "Anatomy-derived finite-element volume conductor, multicompartment cable models and reciprocity-based ECAP observation model",
            DATASET: "Imaging and epidural recordings from six swine",
            PERFORMANCE: "Qualitative mechanistic agreement: morphology and amplitude varied with dorsal-CSF thickness, mediolateral lead location, tonic waveform and contact configuration even at similar neural activation",
            CROSS_SUBJECT: "no: six-animal preclinical modeling study without held-out-animal validation",
            LIMITATIONS: "Six-swine preclinical study with no human validation. ECAP morphology and amplitude can vary at similar underlying neural activation, so waveform amplitude alone is not a direct recruitment, analgesia or pain measure.",
        },
        "evidence": {
            "species": "Sus scrofa domesticus",
            "population": "Six swine with anatomical imaging and epidural spinal recordings",
            "subject_domain": "animal_other",
            "modalities": ["ecap", "simulation_state"],
            "sample_size": 6,
            "target_construct": "technical_signal_quality",
            "target_label": "ECAP morphology and amplitude generated by the anatomical/electrophysiological observation model",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {"status": "verified_primary", "full_text_status": "checked", "split_unit": "animal", "cross_subject": "no", "external_validation": "no", "calibration": "yes", "uncertainty": "not_reported"},
        "risk_flags": ["animal_to_human_transfer_unvalidated", "ecap_not_pain_measure"],
        "locator": "PubMed PMID 40767809, Objectives, Materials and Methods, Results and Conclusions",
        "claim": "A six-swine anatomy-driven forward model shows that ECAP morphology depends on the measurement/stimulation configuration as well as activation.",
        "verified": "The primary abstract confirms imaging/recording sample, finite-element and cable models, reciprocity observation model and anatomical/stimulation dependencies.",
        "permitted": "Use as evidence that an explicit physical ECAP observation operator is required; do not infer human or analgesic validity.",
    },
}


AUDIT_SPECS: dict[str, dict[str, tuple[str, Any, str, str]]] = {
    "S105": {
        "sample": ("reported", "8 chronic-pain participants", "Approach", UPDATES["S105"]["url"]),
        "electrode_geometry": ("reported", "Two percutaneous leads; two most caudal contacts stimulated and remaining contacts recorded", "Approach", UPDATES["S105"]["url"]),
        "stimulation": ("reported", "Amplitude, pulse width and polarity varied by pulse", "Approach and Main results", UPDATES["S105"]["url"]),
        "split_unit": ("reported", "Individual recording/pulse; no held-out-participant test", "Approach", UPDATES["S105"]["url"]),
        "metrics": ("reported", "AUC d'=2.44 versus P2P d'=2.27; current difference about 1.25 mA", "Main results", UPDATES["S105"]["url"]),
    },
    "S159": {
        "sample": ("reported", "2 patients; 9 months; 208336 retained signals; 900 settings", "Methods and Results tables", UPDATES["S159"]["url"]),
        "electrode_geometry": ("unavailable_after_search", None, "Exact contact geometry not recoverable from the primary abstract", UPDATES["S159"]["url"]),
        "stimulation": ("reported", "Biphasic stimulation across multiple neurostimulation scenarios", "Abstract", UPDATES["S159"]["url"]),
        "split_unit": ("reported", "Recording; no held-out-patient validation", "Methods and validation summary", UPDATES["S159"]["url"]),
        "metrics": ("reported", "Bilinear growth-curve E-score; BEAM highest among comparisons", "Abstract", UPDATES["S159"]["url"]),
    },
    "S162": {
        "sample": ("reported", "84 initial sessions: Freshwater 34 and Rosella 50", "Abstract and Results", UPDATES["S162"]["url"]),
        "electrode_geometry": ("reported", "Multiple sensing configurations across the implanted lead; corrected (7,9) and (6,8) recording configurations", "Methods: APM Platform; correction", UPDATES["S162"]["url"]),
        "stimulation": ("reported", "Four to eight anode/cathode and pulse-width candidates ramped to participant discomfort", "Methods: APM Platform", UPDATES["S162"]["url"]),
        "split_unit": ("reported", "Participant/session in two single-arm feasibility studies", "Methods: Study Population", UPDATES["S162"]["url"]),
        "metrics": ("reported", "81/84 success; 11.9 min; SNR 4.6±1.2; +35% SNR; -75% artifact leakage", "Abstract and Results", UPDATES["S162"]["url"]),
    },
    "S236": {
        "sample": ("reported", "68 adults with chronic nonsurgical refractory back pain", "Abstract and Methods", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/"),
        "electrode_geometry": ("not_reported", None, "The clinical subgroup report does not make contact geometry a study variable", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/"),
        "stimulation": ("reported", "ECAP-controlled closed-loop SCS with patient-specific neural-dose target", "Methods", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/"),
        "split_unit": ("reported", "Participant; single-treatment subgroup without concurrent comparator", "Methods", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/"),
        "metrics": ("reported", "12-month responder rates and ECAP target error within 3.5 µV", "Results", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/"),
    },
    "S237": {
        "sample": ("reported", "231 implanted; 220 with required outcome and device data at 22 US sites", "Methods and supplemental Table 1", "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051"),
        "electrode_geometry": ("not_reported", None, "Lead/contact geometry is not the reported comparison variable", "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051"),
        "stimulation": ("reported", "EVOKE ECAP-controlled SCS with neural-dose target", "Methods", "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051"),
        "split_unit": ("reported", "Participant; prospective single-arm observational cohort", "Study design and population", "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051"),
        "metrics": ("reported", "Dose ratio about 1.3; dose accuracy 2.8 µV; VAS and multidomain MCID outcomes", "Results", "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051"),
    },
    "S239": {
        "sample": ("reported", "42 participants in the intent-to-treat set", "Abstract", UPDATES["S239"]["url"]),
        "electrode_geometry": ("not_reported", None, "Geometry is discussed as changing electrode-to-cord spacing, not extracted as a fixed configuration; Abstract", UPDATES["S239"]["url"]),
        "stimulation": ("reported", "ECAP-controlled closed-loop versus open-loop SCS in randomized crossover periods", "Abstract and NCT04765735 protocol", UPDATES["S239"]["url"]),
        "split_unit": ("reported", "Participant; randomized single-blind crossover", "Abstract", UPDATES["S239"]["url"]),
        "metrics": ("reported", "97.6% reduced sensation; lower CI 87.4%; 37/42 preference; ECAP SD 8.72 versus 19.95 µV", "Abstract", UPDATES["S239"]["url"]),
    },
    "S279": {
        "sample": ("not_applicable", None, "Non-empirical framework article; Abstract", UPDATES["S279"]["url"]),
        "electrode_geometry": ("not_applicable", None, "Framework does not report an experimental electrode configuration; Abstract", UPDATES["S279"]["url"]),
        "stimulation": ("reported", "Generic physiologic closed-loop neuromodulation controller", "Rationale", UPDATES["S279"]["url"]),
        "split_unit": ("not_applicable", None, "No empirical train/test or cohort split; Abstract", UPDATES["S279"]["url"]),
        "metrics": ("not_applicable", None, "No empirical performance result is claimed; Abstract", UPDATES["S279"]["url"]),
    },
    "S356": {
        "sample": ("reported", "One male in his 40s", "Case Presentation pp. 2-4", "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf"),
        "electrode_geometry": ("reported", "One 12-contact lead placed at T7", "Case Presentation pp. 2-4", "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf"),
        "stimulation": ("reported", "Five-day ECAP-controlled closed-loop trial with reported pulse parameters and target", "Case Presentation pp. 2-4", "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf"),
        "split_unit": ("not_applicable", None, "Single uncontrolled case; Case Presentation", "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf"),
        "metrics": ("reported", "24.2 million adjustments, 100% utilization and short-term NRS/function changes", "Case Presentation and Conclusions", "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf"),
    },
    "S360": {
        "sample": ("reported", "15 selected day-0 responders; 13 implanted; 11 complete at 12 months", "Abstract and Methods", UPDATES["S360"]["url"]),
        "electrode_geometry": ("reported", "One or two 12-contact percutaneous leads in the dorsal epidural space", "Methods: Participants", UPDATES["S360"]["url"]),
        "stimulation": ("reported", "ECAP-controlled closed-loop SCS with day-0 calibration and permanent-phase logs", "Methods: neural metrics", UPDATES["S360"]["url"]),
        "split_unit": ("reported", "Participant; selected single-center longitudinal subgroup", "Methods and Limitations", UPDATES["S360"]["url"]),
        "metrics": ("reported", "Pain reduction, responder rate, multidomain outcomes and ECAP neural-dose metrics through 12 months", "Results", UPDATES["S360"]["url"]),
    },
    "S363": {
        "sample": ("reported", "Imaging and epidural recordings from six swine", "Materials and Methods", UPDATES["S363"]["url"]),
        "electrode_geometry": ("reported", "Imaging-derived dorsal-CSF thickness and mediolateral lead location represented in the FEM", "Results", UPDATES["S363"]["url"]),
        "stimulation": ("reported", "Tonic waveform and contact configuration coupled to multicompartment cable models", "Materials and Methods and Results", UPDATES["S363"]["url"]),
        "split_unit": ("reported", "Animal; no held-out-animal validation reported", "Materials and Methods", UPDATES["S363"]["url"]),
        "metrics": ("reported", "Qualitative morphology/amplitude dependence at similar modeled neural activation", "Results and Conclusions", UPDATES["S363"]["url"]),
    },
}


def _audit() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for source_id, dimensions in AUDIT_SPECS.items():
        extraction: dict[str, Any] = {}
        for name, (state, value, locator, url) in dimensions.items():
            extraction[name] = {
                "state": state,
                "value": value,
                "reason": "Value extracted from the primary source." if state == "reported" else locator,
                "checked_at": DATE,
                "locators": [{"url": url, "locator": locator}],
            }
        entries.append({"source_id": source_id, "extraction": extraction})
    return {
        "meta": {
            "schema_version": "1.0.0",
            "generated_at": DATE,
            "records_count": len(entries),
            "scope": "Core empirical and framework records used to define the ECAP measurement/operator and closed-loop SCS evidence boundary",
            "gate": "G0_REVISE",
        },
        "construct_boundary": "ECAP is an evoked neural-response/recruitment signal whose observed waveform depends on anatomy, stimulation, electrode geometry, volume conduction, hardware and artifact processing; it is not a direct pain measure.",
        "entries": entries,
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found: set[str] = set()
    sources: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            found.add(record["id"])
        sources.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    statuses = Counter(source["validation"]["status"] for source in sources)
    records["sources"] = sources
    records["meta"].update({"verified_primary_count": statuses["verified_primary"], "updated_at": DATE})
    by_id = {source["id"]: source for source in sources}

    evidence = load_json(data_dir / "evidence-matrix.json")
    for source_id, spec in UPDATES.items():
        source = by_id[source_id]
        payload = {
            "batch_id": BATCH_ID,
            "claim": spec["claim"],
            "target_variable": source["evidence"]["target_label"],
            "population_or_data": source["evidence"]["population"],
            "source_ids": [source_id],
            "verified_evidence": spec["verified"],
            "limitations": source[LIMITATIONS],
            "permitted_conclusion": spec["permitted"],
            "locators": [{"source_id": source_id, "url": spec["url"], "locator": spec["locator"]}],
        }
        matching = [row for row in evidence["rows"] if row.get("source_ids") == [source_id]]
        if matching:
            for row in matching:
                row.update(payload)
        else:
            evidence["rows"].append(payload)
    evidence["meta"]["generated_at"] = DATE

    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in UPDATES:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
        if any(source_id in UPDATES for source_id in cluster.get("состав_кластера", [])):
            cluster["validation"]["checked_at"] = DATE
            cluster["content_review"]["checked_at"] = DATE
    clusters["meta"]["updated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append({
        "search_id": "ECAP-MEASUREMENT-CORE-2026-09-24-01",
        "date": DATE,
        "stream": "ECAP sample, electrode geometry, stimulation, split and metric extraction",
        "query": "exact title/DOI followed by PubMed, PMC, publisher and ClinicalTrials primary material",
        "urls_reviewed": [spec["url"] for spec in UPDATES.values()],
        "source_ids": sorted(UPDATES),
        "decision": "core measurement records re-extracted; all five mandatory dimensions now have reported or terminal states with primary locators",
    })
    validation_log["meta"]["checked_at"] = DATE

    audit_report = load_json(data_dir / "audit-report.json")
    audit_report["current_corpus"]["validation_statuses"] = dict(sorted(statuses.items()))
    audit_report["meta"]["generated_at"] = DATE
    audit_report["ecap_scs_measurement_audit"] = {
        "checked_at": DATE,
        "source_ids": sorted(AUDIT_SPECS),
        "dimensions": ["sample", "electrode_geometry", "stimulation", "split_unit", "metrics"],
        "artifact": "ecap-scs-audit.json",
        "finding": "ECAP waveform and dose are kept separate from pain and clinical response; all dimensions are terminally resolved with primary locators.",
    }

    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(sources))
    completeness["meta"]["generated_at"] = DATE
    return {
        "records.json": records,
        "evidence-matrix.json": evidence,
        "clusters.json": clusters,
        "validation-log.json": validation_log,
        "audit-report.json": audit_report,
        "completeness-report.json": completeness,
        "ecap-scs-audit.json": _audit(),
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-ecap-measurement-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        report = validate_repository(target)
        if not report["ok"]:
            raise ValueError("; ".join(report["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ecap-measurement-core-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(UPDATES), "audit_records": len(AUDIT_SPECS), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
