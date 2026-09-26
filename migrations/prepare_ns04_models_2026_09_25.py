"""Prepare two primary NS-04 model/perturbation studies for canonical review."""

# ruff: noqa: E501 -- primary-source locators are intentionally explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data/staging/inbox"
DATE = "2026-09-25"

SOURCES = [
    {
        "file": "ns04-ozdil-2026.json",
        "id": "S782",
        "doi": "10.1038/s41467-026-72152-x",
        "pmid": "42026054",
        "pmcid": "PMC13314972",
        "url": "https://www.nature.com/articles/s41467-026-72152-x",
        "authors": "Pelin G. Özdil; Javier Arreguit; Cécile Scherrer; Felix Hurtak; Auke Ijspeert; Pavan Ramdya",
        "year": 2026,
        "journal": "Nature Communications 17:5617",
        "modality": "Adult Drosophila brain/VNC connectomes, optogenetic JO-F stimulation and measured head/antenna kinematics",
        "task": "Predict bilateral versus unilateral antennal grooming coordination from a connectome-derived dynamic network",
        "method": "Leaky-integrator connectome-derived neural network with fitted cell-type parameters and motor decoders; virtual JO-F inputs were compared with experimental optogenetic kinematics",
        "dataset": "Adult fly grooming-circuit connectome and optogenetically stimulated kinematics from 10 training flies with forelegs amputated; held-out test recordings are described separately",
        "performance": "Model outputs were evaluated against a held-out test kinematic dataset; this is a fly behavior comparison, not an independent human or pain-outcome test",
        "limitations": "The fitted network is specific to antennal grooming. Foreleg amputation simplified the training assay. Model fit does not establish nociception, subjective pain, human ECAP or SCS response. The MANC v1.2.1 reference is for a supplementary VNC analysis in this paper, not the source release of S740 matrices.",
        "population": "Adult Drosophila connectome specimens and separate flies in optogenetic grooming experiments",
        "sample": "10 flies in the optogenetic training dataset; other assays have separate denominators",
        "target": "Head and antennal kinematics during antennal grooming",
        "modalities": ["connectome", "neural_activity", "movement_pose", "behavior", "simulation_state"],
        "role": "simulation_foundation",
        "locators": {
            "method": "Results, Simulating a connectome-derived antennal grooming network; Methods, Model parameters and training",
            "dataset": "Results, Figure 5A-B; Methods, Connectome analysis and model training",
            "performance": "Results, Figure 5B; Supplementary Figure 10C; held-out test comparison",
            "limitations": "Results, Figure 5A; Methods, Connectome analysis: MANC v1.2.1 in Supplementary Figure 7G-H",
        },
    },
    {
        "file": "ns04-sapkal-2024.json",
        "id": "S783",
        "doi": "10.1038/s41586-024-07854-7",
        "pmid": "39358520",
        "pmcid": "PMC11446846",
        "url": "https://www.nature.com/articles/s41586-024-07854-7",
        "authors": "Neha Sapkal; Nino Mancini; Divya Sthanu Kumar; Nico Spiller; Kazuma Murakami; Gianna Vitelli; Benjamin Bargeron; Kate Maier; Katharina Eichler; Gregory S. X. E. Jefferis; Philip K. Shiu; Gabriella R. Sterne; Salil S. Bidaye",
        "year": 2024,
        "journal": "Nature 634:191–200",
        "modality": "Adult Drosophila FlyWire connectome, Brian2 spiking simulation, optogenetic perturbation, calcium imaging and walking/halting behavior",
        "task": "Explain distinct walk-OFF and brake circuit mechanisms that halt fly walking during feeding or grooming",
        "method": "Connectome-constrained leaky integrate-and-fire model with synapse counts and predicted neurotransmitter signs; virtual activation/silencing and separate fly imaging/behavioral perturbations",
        "dataset": "FlyWire adult brain connectivity with separate adult fly feeding, grooming, calcium-imaging and leg-kinematic experiments; assay-specific denominators",
        "performance": "Simulated neural recruitment and effects of FG/BB silencing were compared with targeted imaging and fly behavior; no single independent model-prediction score or human test is reported",
        "limitations": "Simulated firing rates and optogenetic fly experiments address walking halt, not nociception, subjective pain, ECAP or SCS. The checked article does not provide a single whole-study animal denominator or an independent human cohort.",
        "population": "Adult Drosophila FlyWire brain graph and distinct experimental flies in feeding/grooming assays",
        "sample": "Assay-specific denominators, including 4–9 flies per genotype for Figure 5b imaging and 27–40 for Figure 5e behavior; no one whole-study N",
        "target": "Walking halt and neural recruitment during feeding or grooming",
        "modalities": ["connectome", "neural_activity", "movement_pose", "behavior", "simulation_state"],
        "role": "simulation_foundation",
        "locators": {
            "method": "Results, Figure 3 and Figure 5; Methods, Connectome-constrained modelling",
            "dataset": "Methods, Connectome-constrained modelling; Figure 5 legend and Supplementary Table 1",
            "performance": "Results, Figure 5a-h and Extended Data Figure 9; Methods, Connectome-constrained modelling",
            "limitations": "Abstract; Results, Figure 5; Discussion, model limitations and context-specific halting",
        },
    },
]


def prepare(spec: dict) -> Path:
    path = INBOX / spec["file"]
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["id"] != "S782" or record["название"] is None:
        raise ValueError(f"Unexpected candidate template: {path}")
    record.update({
        "id": spec["id"],
        "авторы": spec["authors"],
        "год": spec["year"],
        "издание": spec["journal"],
        "модальность": spec["modality"],
        "задача": spec["task"],
        "метод": spec["method"],
        "датасет": spec["dataset"],
        "производительность": spec["performance"],
        "кросс_субъект": "not_applicable: fly circuit model and experiments, no human participant prediction",
        "релевантность": 4,
        "ограничения": spec["limitations"],
        "тип_источника": "метод",
    })
    record["identifiers"].update({"doi": spec["doi"], "pmid": spec["pmid"], "exact_url": spec["url"]})
    record["provenance"].update({
        "import_source": f"NS-04 primary Nature full text and Europe PMC {spec['pmcid']} bibliographic record",
        "retrieved_at": DATE,
        "search_stream": "NS-04",
        "query_or_seed": "Drosophila connectome-derived model optogenetic behavioral comparator",
        "iteration": 1,
    })
    record["evidence"].update({
        "species": "Drosophila melanogaster",
        "population": spec["population"],
        "subject_domain": "drosophila_adult",
        "modalities": spec["modalities"],
        "sample_size": spec["sample"],
        "target_construct": "not_applicable",
        "target_label": spec["target"],
        "access_status": "open",
        "evidence_role": spec["role"],
    })
    record["validation"].update({
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "not_reported",
        "cross_subject": "not_applicable",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "exclusion_reason": None,
        "notes": f"Primary Nature full text checked; PubMed {spec['pmid']}. Model/behavior comparison is restricted to adult flies. A held-out test set, where reported, is not a human or independent-site validation.",
    })
    record["relations"] = []
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated", "future_or_recent_record_requires_recheck"] if spec["year"] == 2026 else ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    for key, resolution in record["field_resolution"].items():
        if key.startswith("identifiers.") and key not in {"identifiers.doi", "identifiers.pmid", "identifiers.exact_url"}:
            continue
        if key.startswith("provenance.") or key.startswith("validation."):
            continue
        locator_key = key if key in spec["locators"] else key.removeprefix("evidence.")
        locator = spec["locators"].get(locator_key, "Article abstract, Results and Methods; see source-specific record text")
        resolution["locators"] = [{"url": spec["url"], "locator": locator}]
        resolution["reason"] = "Checked against the primary article; no cross-species clinical inference."
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": f"https://pubmed.ncbi.nlm.nih.gov/{spec['pmid']}/", "locator": "PMID, DOI and article citation"}
    ]
    record["field_resolution"]["validation.split_unit"].update({
        "state": "not_reported", "value": None,
        "reason": "The checked text does not establish a participant-independent or external-site split for the model comparison.",
        "locators": [{"url": spec["url"], "locator": "Methods, model training and evaluation"}],
    })
    atomic_write_json(path, record)
    return path


def main() -> None:
    for spec in SOURCES:
        print(f"Prepared {spec['id']}: {prepare(spec)}")


if __name__ == "__main__":
    main()
