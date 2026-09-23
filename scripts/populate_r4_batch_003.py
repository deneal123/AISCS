"""Populate the third relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-003.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S220": alias(
            "S220",
            "S272",
            "CN122075919A - Closed-loop pain management system",
            "https://patents.google.com/patent/CN122075919A/en",
        ),
        "S221": alias(
            "S221",
            "S273",
            "MenstruEase: Closed-Loop Smart TENS System",
            "https://doi.org/10.1002/adsu.70449",
        ),
        "S245": canonical(
            "S245",
            "verified_metadata",
            "A wearable pain relief device and remote monitoring system therefor",
            "https://patents.google.com/patent/CN120478838B/en",
            patent_id="CN120478838B",
            source="China patent metadata",
            note="Patent identity and translated title are confirmed. No empirical clinical validation or support for efficacy claims was established.",
            target="clinical_function",
            role="context_only",
            risks=["patent_not_empirical_evidence", "metadata_only"],
            claim="CN120478838B is a granted Chinese patent for a wearable pain-relief device and remote monitoring system.",
        ),
        "S350": alias(
            "S350",
            "S363",
            "Anatomical Data Driven Modeling of ECAP (Swine)",
            "https://pubmed.ncbi.nlm.nih.gov/40767809/",
        ),
        "S022": canonical(
            "S022",
            "verified_primary",
            "Machine learning for discovery of clinical pain biomarkers following spinal cord injury",
            "https://pubmed.ncbi.nlm.nih.gov/41539462/",
            doi="10.1016/j.expneurol.2026.115649",
            authors="Roxana Florea; Ki-Soo Jeong; Carl Y Saab",
            source="Experimental Neurology",
            note="This is a review and position article, not a biomarker-validation cohort. It argues for multimodal composite biomarkers and cautions against reducing pain to physiology alone.",
            target="self_reported_pain",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The review supports multimodal composite SCI-pain biomarkers while warning that physiological features alone omit cognitive, emotional, demographic and cultural dimensions.",
        ),
        "S024": rejected(
            "S024",
            "Pain Sense: Intelligent Pain Mapping System for Spinal Cord Injuries",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Pain+Sense%22+%22Spinal+Cord+Injuries%22",
            "No uniquely identifiable primary publication or registered dataset with this exact title was found.",
        ),
        "S160": alias(
            "S160",
            "S363",
            "Anatomical Data Driven Modeling of ECAP Recordings",
            "https://pubmed.ncbi.nlm.nih.gov/40767809/",
        ),
        "S098": canonical(
            "S098",
            "verified_metadata",
            "Machine learning to optimize spinal cord stimulation",
            "https://patents.google.com/patent/US11666761B2/en",
            patent_id="US11666761B2",
            authors="Michael A. Moffitt; Natalie A. Brill; Jianwen Gu; Juan Gabriel Hincapie Ordonez; Changfang Zhu; Hemant Bokil; Stephen Carcieri",
            source="Google Patents / USPTO publication metadata",
            note="The patent describes optimization concepts and possible feedback measures. It is not empirical evidence that an ML optimizer improves patient outcomes.",
            target="scs_response",
            role="context_only",
            risks=["patent_not_empirical_evidence", "metadata_only"],
            claim="US11666761B2 documents a patent family for machine-learning optimization of spinal-cord-stimulation parameters.",
        ),
        "S161": canonical(
            "S161",
            "verified_primary",
            "Machine Learning in Spinal Cord Stimulation for Chronic Pain",
            "https://pubmed.ncbi.nlm.nih.gov/37219574/",
            doi="10.1227/ons.0000000000000774",
            authors="Varun Hariharan; Tessa A Harland; Christopher Young; Amit Sagar; Maria Merlano Gomez; Julie G Pilitsis",
            source="Operative Neurosurgery",
            note="Narrative review of ML applications in SCS; it does not itself externally validate a response-prediction model.",
            target="scs_response",
            role="context_only",
            risks=["missing_cross_subject_validation"],
            claim="The review surveys ML uses for SCS candidate selection, trial response and programming optimization.",
        ),
        "S373": alias(
            "S373",
            "S161",
            "Machine Learning in SCS for Pain (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/37219574/",
        ),
        "S241": canonical(
            "S241",
            "verified_metadata",
            "ECAP-filtered neuromodulation waveform matching",
            "https://patents.google.com/patent/US20250099764A1/en",
            patent_id="US20250099764A1",
            source="Google Patents / USPTO application metadata",
            note="Patent application describing waveform matching after filtering ECAP-related components. It provides no clinical proof of pain measurement or SCS efficacy.",
            target="technical_signal_quality",
            role="context_only",
            risks=["patent_not_empirical_evidence", "ecap_not_pain_measure", "metadata_only"],
            claim="US20250099764A1 describes filtering and matching of recorded neuromodulation waveforms.",
        ),
        "S240": canonical(
            "S240",
            "verified_metadata",
            "Systems and methods for providing neurostimulation therapy using multi-dimensional patient features",
            "https://patents.google.com/patent/US20230123383A1/en",
            patent_id="US20230123383A1",
            source="Google Patents / USPTO application metadata",
            note="Patent application describing multidimensional patient features and AI/ML-assisted neurostimulation. It is not outcome-validation evidence.",
            target="scs_response",
            role="context_only",
            risks=["patent_not_empirical_evidence", "metadata_only"],
            claim="US20230123383A1 proposes neurostimulation control using multidimensional physiological and patient features.",
        ),
        "S018": rejected(
            "S018",
            "Estimation and Localization of Chronic Pain level from EEG Signals",
            "https://dl.acm.org/action/doSearch?AllField=%22Estimation+and+Localization+of+Chronic+Pain+level+from+EEG+Signals%22",
            "No exact ACM record, DOI, authorship record or stable primary publication was found for the supplied title.",
        ),
        "S045": canonical(
            "S045",
            "verified_primary",
            "EEG-Based Pain Classification via Sample Selection to Mitigate Subjective Label Bias",
            "https://pubmed.ncbi.nlm.nih.gov/42118625/",
            doi="10.1109/TNSRE.2026.3692232",
            authors="Euijin Jung; Sung Chan Jun; Jinung An",
            source="IEEE Transactions on Neural Systems and Rehabilitation Engineering",
            note="Forty-one participants received controlled thermal stimuli and supplied NRS labels. Five-fold validation and unseen stimulus types do not by themselves prove transfer to independent clinical cohorts.",
            target="experimental_pain_class",
            role="human_validation",
            risks=["missing_cross_subject_validation"],
            claim="The study evaluates reliability-aware EEG sample selection on 41 participants with self-reported thermal-pain labels.",
        ),
        "S058": alias(
            "S058",
            "S045",
            "EEG-Based Pain Classification via Sample Selection",
            "https://pubmed.ncbi.nlm.nih.gov/42118625/",
        ),
        "S107": alias(
            "S107",
            "S167",
            "Circuit Reconstruction of nociceptive circuits in fly CNS",
            "https://scholar.google.com/scholar?q=%22Circuit+Reconstruction%22+Jones+FlyWire",
        ),
        "S283": alias(
            "S283",
            "S167",
            "Circuit Reconstruction (Jessica Jones, 2026)",
            "https://scholar.google.com/scholar?q=%22Circuit+Reconstruction%22+%22Jessica+Jones%22+FlyWire",
        ),
        "S348": alias(
            "S348",
            "S167",
            "Circuit Reconstruction (Jessica Jones, 2026)",
            "https://scholar.google.com/scholar?q=%22Circuit+Reconstruction%22+%22Jessica+Jones%22+FlyWire",
        ),
        "S017": canonical(
            "S017",
            "verified_metadata",
            "Toward Efficient ECG-Based Pain Intensity Recognition: An End-to-End Neural Network Using Multiple Temporal Feature Compression and Fusion",
            "https://doi.org/10.1109/JIOT.2025.3590401",
            doi="10.1109/JIOT.2025.3590401",
            authors="Rongjian Qiu; Kan Xie; Shengli Xie; Junjie Yang; Yuan Xie; Shihan Qiu; Wenfang Bai",
            source="IEEE Internet of Things Journal",
            note="Bibliographic identity and BioVid evaluation are confirmed from indexing metadata; the publisher full text was not checked, so reported performance is not promoted to a verified claim.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["metadata_only"],
            claim="The indexed article evaluates an ECG pain-intensity architecture on BioVid.",
        ),
        "S019": rejected(
            "S019",
            "DeepPainSense: A Real-Time, Explainable Multimodal System for Chronic Pain and Emotional State Detection",
            "https://scholar.google.com/scholar?q=%22DeepPainSense%22+%22Chronic+Pain%22",
            "Only an inconsistent ResearchGate entry was found; no stable IEEE record, DOI or primary publication could be confirmed.",
        ),
        "S023": canonical(
            "S023",
            "verified_primary",
            "Generalisation of EEG-Based Pain Biomarker Classification for Predicting Central Neuropathic Pain in Subacute Spinal Cord Injury",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC11759196/",
            doi="10.3390/biomedicines13010213",
            authors="Keri Anderson; Sebastian Stein; Ho Suen; Mariel Purcell; Maurizio Belci; Euan McCaughey; Ronali McLean; Aye Khine; Aleksandra Vuckovic",
            source="Biomedicines",
            note="Two SCI datasets were recorded under similar protocols. Cross-dataset validation accuracy was 66.6%, materially below within-dataset estimates; this is prognostic neuropathic-pain evidence, not momentary pain measurement.",
            target="clinical_function",
            role="human_validation",
            risks=[],
            claim="The study tests EEG markers of later central neuropathic pain across two independently collected subacute-SCI datasets and reports 66.6% cross-dataset validation accuracy.",
        ),
        "S073": rejected(
            "S073",
            "Enhanced deep learning framework for real-time pain assessment",
            "https://dl.acm.org/action/doSearch?AllField=%22Enhanced+deep+learning+framework+for+real-time+pain+assessment%22",
            "No exact ACM primary record, DOI or uniquely identifiable publication was found.",
        ),
        "S115": alias(
            "S115",
            "S073",
            "Enhanced deep learning framework for real-time pain assessment",
            "https://dl.acm.org/action/doSearch?AllField=%22Enhanced+deep+learning+framework+for+real-time+pain+assessment%22",
        ),
    }
    decisions["S022"]["updates"]["identifiers"]["pmid"] = "41539462"
    decisions["S022"]["updates"]["год"] = 2026
    decisions["S098"]["updates"]["год"] = 2023
    decisions["S161"]["updates"]["identifiers"]["pmid"] = "37219574"
    decisions["S161"]["updates"]["год"] = 2023
    decisions["S241"]["updates"]["год"] = 2025
    decisions["S240"]["updates"]["год"] = 2023
    decisions["S045"]["updates"]["identifiers"]["pmid"] = "42118625"
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
