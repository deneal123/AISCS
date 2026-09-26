"""Prepare the primary FANC source for staged curation."""

# ruff: noqa: E501 -- keep source locators and scientific boundaries explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns01-fanc-azevedo-2024.json"
URL = "https://www.nature.com/articles/s41586-024-07389-x"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S773":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Anthony Azevedo; Ellen Lesser; Jasper S. Phelps; Brandon Mark; John C. Tuthill; et al.",
            "год": 2024,
            "издание": "Nature 631:360–368",
            "модальность": "Serial electron-microscopy connectome of an adult female Drosophila ventral nerve cord; genetic motor-neuron drivers and X-ray holographic nanotomography for muscle-target atlas",
            "задача": "Reconstruct female ventral nerve cord circuits and map motor-neuron muscle targets for leg and wing movement",
            "метод": "Automated neuron segmentation and synapse identification in an adult female VNC EM volume; mapping motor-neuron targets with genetic driver lines and X-ray holographic nanotomography",
            "датасет": "FANC adult female ventral nerve cord EM reconstruction; publisher reports roughly 45 million synapses and 14,600 neuronal cell bodies. The author-maintained FANC wiki pins the Nature paper analysis to CAVE materialization v840 on 17 January 2024; this does not pin S740's export.",
            "производительность": "Resource reconstruction and take-off circuit analysis; no dynamical pain, ECAP or SCS prediction metric",
            "кросс_субъект": "not_applicable: anatomical reconstruction, not trained cross-subject prediction",
            "релевантность": 4,
            "ограничения": "The accessible publisher abstract and data-availability section identify the FANC graph and motor atlas, but full methods are subscription gated in this review. The author wiki pins this Nature paper to CAVE v840; S740's FANC processed matrix has no documented CAVE materialization and must not inherit v840. The reported circuits concern leg/wing motor control and take-off, not nociceptive subjective pain or human ECAP/SCS outcomes.",
            "тип_источника": "метод",
        }
    )
    record["identifiers"].update(doi="10.1038/s41586-024-07389-x", exact_url=URL)
    record["provenance"].update(
        import_source="NS-01 primary Nature publisher page",
        retrieved_at=DATE,
        search_stream="NS-01",
        query_or_seed="female Drosophila ventral nerve cord FANC primary connectome article",
        iteration=3,
    )
    record["evidence"].update(
        species="Drosophila melanogaster",
        population="Adult female VNC EM reconstruction and motor-neuron atlas",
        subject_domain="drosophila_adult",
        modalities=["connectome"],
        sample_size=None,
        target_construct="not_applicable",
        target_label="Anatomical VNC circuits and leg/wing motor targets",
        access_status="registration_required",
        evidence_role="dataset_descriptor",
    )
    record["validation"].update(
        status="partially_verified",
        screening_status="included_context",
        full_text_status="metadata_only",
        checked_at=DATE,
        split_unit="not_applicable",
        cross_subject="not_applicable",
        external_validation="not_applicable",
        calibration="not_applicable",
        uncertainty="not_reported",
        exclusion_reason=None,
        notes="Primary Nature abstract, Data availability, Code availability and figure captions checked. Full methods remain subscription gated at the publisher page. FANC version used as an input by S740 remains unpinned.",
    )
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    for path, section in {
        "авторы": "Article byline",
        "год": "Published: 26 June 2024",
        "издание": "Citation header: Nature 631, 360–368 (2024)",
        "модальность": "Abstract; Figure 1–6 captions",
        "задача": "Abstract",
        "метод": "Abstract: segmentation, synapses and muscle-target mapping",
        "датасет": "Abstract; Data availability",
        "производительность": "Abstract: anatomical resource and take-off circuits",
        "кросс_субъект": "Abstract: no predictive participant split",
        "ограничения": "Abstract; Data availability; subscription-content notice",
        "evidence.species": "Abstract: adult female Drosophila melanogaster VNC",
        "evidence.population": "Abstract: adult female VNC reconstruction",
        "evidence.sample_size": "Abstract: no independent-animal denominator given",
        "evidence.target_construct": "Abstract: anatomical and motor-circuit resource",
        "evidence.target_label": "Abstract and Figure 3–6 captions",
        "validation.split_unit": "Abstract: anatomical resource, no training split",
        "validation.cross_subject": "Abstract: no cross-subject prediction",
        "validation.external_validation": "Abstract: no external predictive test",
        "validation.calibration": "Abstract: no predictive probabilities",
        "validation.uncertainty": "Abstract: no model uncertainty summary",
        "validation.notes": "Abstract; Data availability; access notice",
    }.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the accessible primary publisher page; full methods access is limited."
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update(
        state="not_reported",
        value=None,
        reason="The accessible publisher abstract reports graph size, not an independent-animal sample denominator.",
    )
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
