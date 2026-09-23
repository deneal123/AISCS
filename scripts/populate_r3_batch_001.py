"""Populate the first relevance-3 review batch from primary-source checks."""

from __future__ import annotations

from pathlib import Path

from populate_r4_batch_001 import TODAY, alias, canonical, rejected

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "relevance-3" / "batches" / "r3-batch-001.json"


def main() -> None:
    payload = load_json(PATH)
    decisions = {
        "S201": canonical(
            "S201",
            "verified_primary",
            "Infinite Sugar",
            "https://github.com/cnqso/infinite-sugar",
            authors="cnqso",
            source="GitHub software and artwork repository",
            note="The repository is a browser artwork using FlyWire connectivity and simplified LIF-style activity. Several body movements use supplied patterns; it is not a validated whole-brain emulation or nociception model.",
            target="not_applicable",
            role="context_only",
            risks=["synthetic_only", "claim_not_supported"],
            claim="Infinite Sugar is an inspectable software artwork that visualizes connectome-derived activity in an embodied virtual fly.",
        ),
        "S137": alias(
            "S137",
            "S201",
            "Infinite Sugar: Whole-brain emulation artwork",
            "https://github.com/cnqso/infinite-sugar",
        ),
        "S234": alias(
            "S234",
            "S201",
            "Infinite Sugar: Whole-brain emulation artwork (extended)",
            "https://github.com/cnqso/infinite-sugar",
        ),
        "S296": canonical(
            "S296",
            "partially_verified",
            "Eon Systems: mouse-brain emulation programme",
            "https://eon.systems/updates/first-multi-behavior-brain-upload",
            authors="Eon Systems",
            source="Eon Systems technical update",
            note="The company states that mouse emulation is a future target and that data collection is underway. The page does not document a completed digital mouse-brain emulation or independent validation.",
            target="not_applicable",
            role="context_only",
            risks=["news_or_secondary_source", "synthetic_only", "claim_not_supported"],
            claim="Eon publicly describes a programme targeting future mouse-brain emulation after its embodied-fly work.",
        ),
        "S335": alias(
            "S335",
            "S296",
            "Eon Systems: Digital emulation of mouse brain (extended)",
            "https://eon.systems/updates/first-multi-behavior-brain-upload",
        ),
        "S395": alias(
            "S395",
            "S296",
            "Eon Systems: Digital emulation of mouse brain (final)",
            "https://eon.systems/updates/first-multi-behavior-brain-upload",
        ),
        "S026": canonical(
            "S026",
            "verified_metadata",
            "Novel behavioral assay of noxious heat responses in Drosophila using decapitated flies",
            "https://www.jstage.jst.go.jp/article/hikakuseiriseika/31/4/31_151/_pdf",
            authors="Hirono Ohashi; Takaomi Sakai",
            source="11th International Congress of Neuroethology 2014 abstract",
            note="The exact conference abstract is identifiable, but no full peer-reviewed article or detailed protocol and results were located. The original card had no year and was misclassified as SCS-specific.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["metadata_only", "animal_to_human_transfer_unvalidated"],
            claim="A 2014 conference abstract reports a decapitated-fly behavioral assay for noxious heat responses.",
        ),
        "S066": canonical(
            "S066",
            "verified_primary",
            "A positive feedback loop between sensory and octopaminergic neurons underlies nociceptive plasticity in Drosophila larvae",
            "https://pubmed.ncbi.nlm.nih.gov/42048383/",
            doi="10.1371/journal.pgen.1012122",
            authors="Jean-Christophe Boivin; Yi Q Zhao; Jiayi Zhu; Jared T Dakin; Jing Ning; Tomoko Ohyama",
            source="PLOS Genetics",
            note="The experiments address experience-dependent sensitization of nocifensive rolling in Drosophila larvae. They do not establish subjective pain or a mapping to human spinal or SCS responses.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="Repeated nociceptor activation and octopaminergic feedback increase sensory gain and nocifensive rolling in Drosophila larvae.",
        ),
        "S094": alias(
            "S094",
            "S066",
            "Positive feedback loop between sensory and octopaminergic neurons",
            "https://pubmed.ncbi.nlm.nih.gov/42048383/",
        ),
        "S227": canonical(
            "S227",
            "verified_primary",
            "MuSACo: Multimodal Subject-Specific Selection and Adaptation for Expression Recognition with Co-Training",
            "https://arxiv.org/abs/2508.12522",
            authors="Muhammad Osama Zeeshan; Natacha Gillet; Alessandro Lameiras Koerich; Marco Pedersoli; Francois Bremond; Eric Granger",
            source="WACV 2026 / arXiv",
            note="The method evaluates subject-specific multimodal expression adaptation on BioVid and StressID. It is an affective-computing baseline, not external clinical pain validation or SCS evidence.",
            target="experimental_pain_class",
            role="method_baseline",
            risks=["preprint"],
            claim="MuSACo selects relevant source subjects and adapts multimodal expression-recognition models to an unlabeled target subject.",
        ),
        "S068": canonical(
            "S068",
            "verified_primary",
            "The fly connectome reveals a path to the effectome",
            "https://pubmed.ncbi.nlm.nih.gov/39358526/",
            doi="10.1038/s41586-024-07982-0",
            authors="Dean A Pospisil; Max J Aragon; Sven Dorkenwald; Arie Matsliah; Amy R Sterling; Philipp Schlegel; Szi-Chieh Yu; Claire E McKellar; Marta Costa; Katharina Eichler; Gregory S X E Jefferis; Mala Murthy; Jonathan W Pillow",
            source="Nature",
            note="The study proposes causal effectome estimation using perturbations and a connectome prior. Simulation validation does not itself supply biological whole-brain dynamics or pain-related labels.",
            target="not_applicable",
            role="simulation_foundation",
            risks=["synthetic_only"],
            claim="The study uses the fly connectome as a prior to improve estimation of causal neural interactions from perturbation data.",
        ),
        "S092": canonical(
            "S092",
            "verified_primary",
            "Drosophila epidermal cells are intrinsically mechanosensitive and modulate nociceptive behavioral outputs",
            "https://pubmed.ncbi.nlm.nih.gov/40353351/",
            doi="10.7554/eLife.95379",
            authors="Jiro Yoshino; Sonali S Mali; Claire R Williams; Takeshi Morita; Chloe E Emerson; Christopher J Arp; Sophie E Miller; Chang Yin; Lydia The; Chikayo Hemmi; Mana Motoyoshi; Kenichi Ishii; Kazuo Emoto; Diana M Bautista; Jay Z Parrish",
            source="eLife",
            note="The work identifies epidermal contributions to larval mechanonociception and sensitization. Behavioral escape remains a nociceptive outcome, not evidence of subjective pain or human transfer.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="Drosophila epidermal cells respond to mechanical stimulation and modulate sensory-neuron activity and nocifensive behavior.",
        ),
        "S252": canonical(
            "S252",
            "verified_primary",
            "Method of the Year 2025: electron microscopy-based connectomics",
            "https://www.nature.com/articles/s41592-025-02988-6",
            doi="10.1038/s41592-025-02988-6",
            source="Nature Methods editorial",
            note="This is an unsigned editorial selecting EM connectomics as Method of the Year, not an empirical FlyWire validation study or evidence about pain, behavior, or transfer.",
            target="not_applicable",
            role="context_only",
            risks=["news_or_secondary_source"],
            claim="Nature Methods selected electron-microscopy-based connectomics as its Method of the Year 2025 and contextualized FlyWire among recent advances.",
        ),
        "S049": canonical(
            "S049",
            "verified_primary",
            "Classification of electrically-evoked potentials in the parkinsonian subthalamic nucleus region",
            "https://pubmed.ncbi.nlm.nih.gov/36792646/",
            doi="10.1038/s41598-023-29439-6",
            authors="Joshua Rosing; Alex Doyle; AnneMarie Brinda; Madeline Blumenfeld; Emily Lecy; Chelsea Spencer; Joan Dao; Jordan Krieg; Kelton Wilmerding; Disa Sullivan; Sendrea Best; Biswaranjan Mohanty; Jing Wang; Luke A Johnson; Jerrold L Vitek; Matthew D Johnson",
            source="Scientific Reports",
            note="Four MPTP-treated non-human primates were used to classify electrode location from STN-region ECAPs. This DBS work concerns Parkinsonian neuroanatomy, not spinal ECAPs, pain, or clinical SCS response.",
            target="ecap_neural_recruitment",
            role="context_only",
            risks=["ecap_not_pain_measure", "animal_to_human_transfer_unvalidated"],
            claim="STN-region electrically evoked potentials vary with stimulation and recording location and support electrode-location classification in four parkinsonian primates.",
        ),
        "S030": canonical(
            "S030",
            "verified_primary",
            "Sensory integration and neuromodulatory feedback facilitate Drosophila mechanonociceptive behavior",
            "https://pubmed.ncbi.nlm.nih.gov/28604684/",
            doi="10.1038/nn.4580",
            authors="Chun Hu; Meike Petersen; Nina Hoyer; Bettina Spitzweck; Federico Tenedini; Denan Wang; Alisa Gruschka; Lara S Burchardt; Emanuela Szpotowicz; Michaela Schweizer; Ananya R Guntur; Chung-Hui Yang; Peter Soba",
            source="Nature Neuroscience",
            note="The circuit study explains modality-specific mechanonociceptive escape in larvae. It does not demonstrate subjective pain or justify direct mapping to human spinal physiology.",
            target="nociceptive_response",
            role="simulation_foundation",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="Mechanosensory integration and short-neuropeptide-F feedback facilitate robust larval mechanonociceptive escape.",
        ),
        "S021": canonical(
            "S021",
            "verified_primary",
            "Recognition and inhibition of dorsal horn nociceptive signals within a closed-loop system",
            "https://pubmed.ncbi.nlm.nih.gov/21096375/",
            doi="10.1109/IEMBS.2010.5626830",
            authors="Aydin Farajidavar; Christopher E Hagains; Yuan B Peng; Khosrow Behbehani; J-C Chiao",
            source="IEEE EMBC 2010",
            note="The animal system detects dorsal-horn spiking responses to brush, pressure and pinch and triggers neurostimulation. It is not a human pain classifier, ECAP measurement, or clinical SCS-outcome study.",
            target="nociceptive_response",
            role="context_only",
            risks=["animal_to_human_transfer_unvalidated"],
            claim="The prototype closes a loop between dorsal-horn nociceptive-spike detection and wireless neurostimulation.",
        ),
        "S028": rejected(
            "S028",
            "The FlyWire Connectome: What a Complete Brain Map Tells Us About Building Conscious AI",
            "https://theconsciousness.ai/posts/flywire-drosophila-connectome-ai-architecture-2024/",
            "The exact item is a speculative secondary blog post, not a peer-reviewed source or primary FlyWire result, and its consciousness claims are not validated evidence.",
        ),
        "S067": alias(
            "S067",
            "S028",
            "FlyWire connectome: building conscious AI",
            "https://theconsciousness.ai/posts/flywire-drosophila-connectome-ai-architecture-2024/",
        ),
        "S097": canonical(
            "S097",
            "verified_primary",
            "Federated Learning in Edge Computing: Vulnerabilities, Attacks, and Defenses—A Survey",
            "https://www.mdpi.com/1424-8220/26/4/1275",
            doi="10.3390/s26041275",
            authors="Sahar Saleh Alhawas; Murad A Rassam",
            source="Sensors",
            note="General structured survey of edge federated-learning security; it contains no pain, SCS, ECAP, or clinical-transfer validation.",
            target="not_applicable",
            role="context_only",
            risks=[],
            claim="The survey categorizes edge-FL vulnerabilities, attack classes, defenses and benchmark gaps under resource constraints.",
        ),
        "S246": canonical(
            "S246",
            "partially_verified",
            "CROSSBRAIN: Distributed and federated cross-modality actuation through advanced nanomaterials and neuromorphic learning",
            "https://cordis.europa.eu/project/id/101070908/reporting",
            doi="10.3030/101070908",
            authors="CROSSBRAIN consortium",
            source="European Commission CORDIS project record",
            note="The official record confirms the funded project, dates and objectives. A grant record is not a peer-reviewed result and does not validate pain assessment, SCS response, or clinical efficacy.",
            target="not_applicable",
            role="context_only",
            risks=["claim_not_supported"],
            claim="CORDIS documents the CROSSBRAIN research programme on distributed multimodal actuation, nanomaterials and neuromorphic learning.",
        ),
    }
    decisions["S026"]["updates"]["год"] = 2014
    decisions["S066"]["updates"]["identifiers"]["pmid"] = "42048383"
    decisions["S227"]["updates"]["identifiers"]["arxiv_id"] = "2508.12522"
    decisions["S068"]["updates"]["identifiers"]["pmid"] = "39358526"
    decisions["S068"]["updates"]["год"] = 2024
    decisions["S092"]["updates"]["identifiers"]["pmid"] = "40353351"
    decisions["S252"]["updates"]["risk_flags"].append("missing_authors")
    decisions["S049"]["updates"]["identifiers"]["pmid"] = "36792646"
    decisions["S049"]["updates"]["год"] = 2023
    decisions["S030"]["updates"]["identifiers"]["pmid"] = "28604684"
    decisions["S030"]["updates"]["год"] = 2017
    decisions["S021"]["updates"]["identifiers"]["pmid"] = "21096375"
    decisions["S097"]["updates"]["identifiers"]["pmid"] = "41755214"
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
