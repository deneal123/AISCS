"""Prepare the primary whole-brain connectome dynamics comparator."""

# ruff: noqa: E501 -- preserve primary method and comparator boundaries.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns02-shiu-brain-model-2024.json"
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11446845/fullTextXML"
PUBLISHER = "https://www.nature.com/articles/s41586-024-07763-9"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S775":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Philip K. Shiu; Gabriella R. Sterne; Nico Spiller; Romain Franconville; Andrea Sandoval; et al.",
            "год": 2024,
            "издание": "Nature 634:210–219",
            "модальность": "Adult Drosophila FlyWire central-brain connectome, predicted neurotransmitter identity, simulated spike activity, optogenetic activation and feeding/grooming observations",
            "задача": "Predict sensorimotor responses in feeding and antennal grooming circuits from a whole-brain connectome model",
            "метод": "Brainwide leaky integrate-and-fire model with alpha-synapse dynamics on connectome weights and predicted excitatory/inhibitory identities; sensory and interneuron activation compared with neural and behavioral experiments",
            "датасет": "Adult FlyWire central-brain connectome with over 125,000 neurons and 50 million synaptic connections; the checked JATS text does not state an immutable FlyWire graph release identifier",
            "производительность": "Model predictions of taste-responsive and feeding-initiating neurons, taste interactions and antennal grooming circuits are tested by optogenetic activation and behavioral or neural observations; no pain, ECAP or SCS metric",
            "кросс_субъект": "not_applicable: connectome simulation and fly experiments, not human participant prediction",
            "релевантность": 4,
            "ограничения": "The model concerns adult central-brain feeding and grooming circuits, not VNC walking or nociceptive subjective pain. Authors caution that absolute model firing rates are unreliable because morphology, receptor dynamics, gap junctions, peptides and neuromodulation are omitted. Fly experiments validate scoped circuit hypotheses, not human ECAP or SCS outcomes. Exact graph release was not found in the checked JATS article.",
            "тип_источника": "метод",
        }
    )
    record["identifiers"].update(doi="10.1038/s41586-024-07763-9", pmid="39358519", exact_url=PUBLISHER)
    record["provenance"].update(
        import_source="NS-02 primary Nature JATS via Europe PMC",
        retrieved_at=DATE,
        search_stream="NS-02",
        query_or_seed="Shiu whole-brain Drosophila LIF FlyWire sensorimotor model",
        iteration=3,
    )
    record["evidence"].update(
        species="Drosophila melanogaster",
        population="Adult central-brain connectome and separate experimental flies in scoped feeding/grooming validations",
        subject_domain="drosophila_adult",
        modalities=["connectome", "neural_activity", "behavior", "simulation_state"],
        sample_size="over 125,000 modeled neurons; experimental animal denominators vary by assay",
        target_construct="not_applicable",
        target_label="Feeding initiation and antennal grooming, not nociceptive protection",
        access_status="open",
        evidence_role="simulation_foundation",
    )
    record["validation"].update(
        status="verified_primary",
        screening_status="included_core",
        full_text_status="checked",
        checked_at=DATE,
        split_unit="not_applicable",
        cross_subject="not_applicable",
        external_validation="no",
        calibration="not_reported",
        uncertainty="not_reported",
        exclusion_reason=None,
        notes="Primary Nature JATS full text checked through Europe PMC PMC11446845. Optogenetic and behavioral tests validate scoped model predictions in flies; this is biological experiment comparison, not a held-out human cohort. The article does not pin a FlyWire graph release in the checked text.",
    )
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Article front matter: byline",
        "год": "Article front matter: 2024",
        "издание": "Article front matter: Nature 634, 210–219",
        "модальность": "Abstract; Methods > Computational model and experimental assays",
        "задача": "Abstract; Results > feeding and grooming",
        "метод": "Methods > Computational model; Neurotransmitter predictions",
        "датасет": "Abstract; Methods > Connectome and computational model",
        "производительность": "Abstract; Results > feeding and grooming comparisons",
        "кросс_субъект": "Methods: fly circuit simulation rather than human prediction",
        "ограничения": "Methods > Computational modelling limitations",
        "evidence.species": "Abstract: adult Drosophila melanogaster",
        "evidence.population": "Methods > computational model and fly validation assays",
        "evidence.sample_size": "Abstract: over 125,000 neurons and 50 million synapses",
        "evidence.target_construct": "Abstract: feeding and grooming rather than nociception",
        "evidence.target_label": "Abstract: feeding initiation and grooming",
        "validation.split_unit": "Methods: no held-out human prediction split",
        "validation.cross_subject": "Methods: fly experiments, no human cross-subject task",
        "validation.external_validation": "Abstract; Results: scoped fly experiments, no independent graph or human cohort",
        "validation.calibration": "Methods: no reported probability calibration",
        "validation.uncertainty": "Methods > Computational modelling limitations",
        "validation.notes": "Abstract; Methods > Computational model and limitations; Data availability",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary full JATS text; circuit and transfer boundaries are explicit."
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["identifiers.pmid"]["locators"] = [{"url": "https://pubmed.ncbi.nlm.nih.gov/39358519/", "locator": "PMID and DOI"}]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
