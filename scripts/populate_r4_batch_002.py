"""Populate the second relevance-4 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-4" / "batches" / "r4-batch-002.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S330": canonical(
            "S330",
            "verified_primary",
            "Towards Personalized Edge-AI for Medicine: Efficient Neuromorphic Frameworks for Seizure Detection and Prediction",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
            doi="10.1101/2025.09.22.25336341",
            authors="Luis Fernando Herbozo Contreras; Leping Yu; Zhaojing Huang; Isabelle Aguilar; Armin Nikpour; Omid Kavehei",
            source="medRxiv",
            note="The work concerns patient-specific seizure detection and prediction on neuromorphic hardware, not pain assessment or SCS-response prediction. It is retained only as methodological context.",
            target="not_applicable",
            role="context_only",
            risks=["preprint"],
            claim="The preprint reports on-device few-shot adaptation for seizure detection and prediction across EEG datasets.",
        ),
        "S345": alias(
            "S345",
            "S330",
            "Towards Personalized Edge-AI (final extended)",
            "https://www.medrxiv.org/content/10.1101/2025.09.22.25336341v2",
        ),
        "S331": alias(
            "S331",
            "S320",
            "Embodied Whole-Brain Spiking Simulation (extended)",
            "https://github.com/rndlabsoy/fly-brain-full",
        ),
        "S394": alias(
            "S394",
            "S320",
            "Embodied Whole-Brain Spiking Simulation (final)",
            "https://github.com/rndlabsoy/fly-brain-full",
        ),
        "S347": alias(
            "S347",
            "S212",
            "Combining brain-wide activity imaging + EM (extended)",
            "https://doi.org/10.1101/2025.09.25.678485",
        ),
        "S363": canonical(
            "S363",
            "verified_primary",
            "Anatomical Data Driven Modeling of Evoked Compound Action Potentials Recordings During Spinal Cord Stimulation in a Swine Model",
            "https://pubmed.ncbi.nlm.nih.gov/40767809/",
            doi="10.1016/j.neurom.2025.06.008",
            authors="Meagan K Brucker-Hahn; Ashlesha Deshmukh; Megan Settell; Justin Chin; Aniruddha Upadhye; Igor Lavrov; Andrew J Shoffstall; Kip A Ludwig; Mingming Zhang; Scott F Lempka",
            source="Neuromodulation",
            note="The model uses imaging and epidural recordings from six swine. ECAP morphology and amplitude depend on stimulation and anatomy and may not directly represent neural recruitment; this is preclinical measurement-model evidence, not pain or outcome evidence.",
            target="ecap_neural_recruitment",
            role="method_baseline",
            risks=["animal_to_human_transfer_unvalidated", "ecap_not_pain_measure"],
            claim="A six-swine anatomical and biophysical model demonstrates strong dependence of modeled ECAPs on stimulation configuration and anatomy.",
        ),
        "S367": alias("S367", "S200", "DOOMFLY (extended)", "https://github.com/nftechie/doomfly"),
        "S399": alias("S399", "S200", "DOOMFLY (final)", "https://github.com/nftechie/doomfly"),
        "S368": canonical(
            "S368",
            "partially_verified",
            "5 amazing visuals show how the male fruit fly's brain map is advancing neuroscience",
            "https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/",
            authors="Michal Januszewski; Viren Jain",
            source="Google Research blog",
            note="The institutional article confirms a male fly brain and ventral-nerve-cord map with more than 166,000 neurons. It is a communications article, not a methods paper, and does not establish a pain simulator or the original claim of an open-source simulation.",
            role="simulation_foundation",
            risks=[
                "news_or_secondary_source",
                "animal_to_human_transfer_unvalidated",
                "claim_not_supported",
            ],
            claim="The institutional project article documents a complete male Drosophila CNS connectome resource exceeding 166,000 neurons.",
        ),
        "S370": alias(
            "S370",
            "S167",
            "Circuit Reconstruction (final)",
            "https://scholar.google.com/scholar?q=%22Circuit+Reconstruction%22+Jones+FlyWire",
        ),
        "S398": alias(
            "S398",
            "S167",
            "Circuit Reconstruction (final extended)",
            "https://scholar.google.com/scholar?q=%22Circuit+Reconstruction%22+Jones+FlyWire",
        ),
        "S242": alias(
            "S242",
            "S279",
            "PCLC case study of ECAP-informed SCS",
            "https://pubmed.ncbi.nlm.nih.gov/42059841/",
        ),
        "S371": alias(
            "S371",
            "S279",
            "PCLC case study of ECAP-informed SCS (extended)",
            "https://pubmed.ncbi.nlm.nih.gov/42059841/",
        ),
        "S372": alias(
            "S372",
            "S099",
            "US12642969B2 - SCI therapy based on ECAP (extended)",
            "https://patents.justia.com/patent/12642969",
        ),
        "S385": alias(
            "S385",
            "S320",
            "Emergent Individuality (final)",
            "https://doi.org/10.5281/zenodo.19152238",
        ),
        "S397": alias(
            "S397",
            "S212",
            "Combining brain-wide imaging + EM (final)",
            "https://doi.org/10.1101/2025.09.25.678485",
        ),
        "S400": alias(
            "S400",
            "S368",
            "Google open-sources fly brain (final)",
            "https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/",
        ),
        "S405": alias(
            "S405",
            "S363",
            "Anatomical Data Driven Modeling (final)",
            "https://pubmed.ncbi.nlm.nih.gov/40767809/",
        ),
        "S410": alias(
            "S410", "S099", "US12642969B2 (final)", "https://patents.justia.com/patent/12642969"
        ),
        "S009": alias(
            "S009",
            "S144",
            "Method and apparatus for adaptive neural interfaces",
            "https://patents.google.com/patent/WO2026146221A1/en",
        ),
        "S060": rejected(
            "S060",
            "Integration of AI into SCS: ethical and data-governance challenges",
            "https://pubmed.ncbi.nlm.nih.gov/?term=%22Integration+of+AI+into+SCS%22",
            "No uniquely identifiable JCDR or PubMed publication with this exact title was found; the generic record cannot support an evidence claim.",
        ),
        "S099": canonical(
            "S099",
            "verified_metadata",
            "Spinal cord injury therapy based on evoked compound action potentials",
            "https://patents.justia.com/patent/12642969",
            patent_id="US12642969B2",
            authors="David A. Dinsmoor; Medtronic, Inc.",
            source="USPTO grant metadata and Justia patent text",
            note="Patent identity, grant date, assignee, inventor and ECAP-controlled SCI-stimulation scope are confirmed. A patent is not empirical evidence of safety, efficacy, pain measurement, or clinical outcome prediction.",
            target="ecap_neural_recruitment",
            role="context_only",
            risks=["patent_not_empirical_evidence", "ecap_not_pain_measure"],
            claim="US12642969B2 describes ECAP-informed adjustment of stimulation parameters for conditions associated with spinal cord injury.",
        ),
        "S100": alias(
            "S100",
            "S144",
            "Predictive analytics pipeline for adaptive neural interfaces",
            "https://patents.google.com/patent/WO2026146221A1/en",
        ),
        "S162": canonical(
            "S162",
            "verified_primary",
            "Next-Generation SCS Programming Platform: Enhancing ECAP Fidelity and Objectivity to Improve Patient Experience",
            "https://link.springer.com/article/10.1007/s40122-025-00808-5",
            doi="10.1007/s40122-025-00808-5",
            authors="Daniel J Parker; Ajay B Antony; Gregory L Smith; Johnathan H Goree; Marc A Russo; Erika A Petersen; Chau M Vu; Paul Verrills; Christopher Gilmore; Leonardo Kapural; Darayus Nanavati; Dean M Karantonis; Jason E Pope",
            source="Pain and Therapy",
            note="Two prospective multicenter single-arm feasibility studies support programming feasibility and signal fidelity. They do not establish comparative analgesic efficacy or prediction of long-term SCS response.",
            target="ecap_neural_recruitment",
            role="scs_ecap_validation",
            risks=["ecap_not_pain_measure"],
            claim="The APM generated a closed-loop program in 81 of 84 initial sessions and improved ECAP signal-quality measures in two single-arm feasibility studies.",
        ),
        "S184": alias(
            "S184",
            "S162",
            "Next-Generation SCS Programming Platform",
            "https://link.springer.com/article/10.1007/s40122-025-00808-5",
        ),
    }
    decisions["S363"]["updates"]["identifiers"]["pmid"] = "40767809"
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
