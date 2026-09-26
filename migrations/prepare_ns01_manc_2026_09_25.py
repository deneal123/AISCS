"""Prepare the primary male adult nerve cord connectome source."""

# ruff: noqa: E501 -- keep primary locators and exact version boundaries explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns01-manc-takemura-2024.json"
URL = "https://elifesciences.org/reviewed-preprints/97769"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S774":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Shin-ya Takemura; Kenneth J. Hayworth; Gary B. Huang; Michal Januszewski; Zhiyuan Lu; Elizabeth C. Marin; et al.",
            "год": 2024,
            "издание": "eLife 13:RP97769, Reviewed Preprint v1 (23 May 2024)",
            "модальность": "Serial electron-microscopy connectome of the male adult Drosophila ventral nerve cord",
            "задача": "Dense reconstruction of the male adult ventral nerve cord and its descending, sensory, premotor and motor connections",
            "метод": "Large-volume serial EM imaging, automated segmentation and synapse identification, neuronal tracing/proofreading and neuPrint access",
            "датасет": "One five-day-old male adult VNC sample, called MANC; about 23,000 traced neurons, 10 million presynaptic TBars and 74 million postsynaptic densities. Reviewed-preprint v1 identifies the neuPrint dataset as MANC without pinning an immutable database release used in S740.",
            "производительность": "Anatomical reconstruction and completion metrics by neuropil; no dynamic pain, ECAP or SCS prediction metric",
            "кросс_субъект": "not_applicable: single-specimen connectome reconstruction, not trained cross-subject prediction",
            "релевантность": 4,
            "ограничения": "The eLife article is a Reviewed Preprint v1, not an independent experimental validation of S740's model. It identifies the public neuPrint MANC dataset but not the exact export/release underlying S740's processed matrix. Motor-control anatomy cannot be interpreted as subjective pain or human ECAP/SCS evidence.",
            "тип_источника": "метод",
        }
    )
    record["identifiers"].update(doi="10.7554/eLife.97769.1", exact_url=URL)
    record["provenance"].update(
        import_source="NS-01 primary eLife reviewed-preprint full text",
        retrieved_at=DATE,
        search_stream="NS-01",
        query_or_seed="MANC male Drosophila VNC Takemura connectome",
        iteration=3,
    )
    record["evidence"].update(
        species="Drosophila melanogaster",
        population="Five-day-old male adult VNC EM specimen",
        subject_domain="drosophila_adult",
        modalities=["connectome"],
        sample_size=1,
        target_construct="not_applicable",
        target_label="Anatomical connectivity of male adult VNC",
        access_status="open",
        evidence_role="dataset_descriptor",
    )
    record["validation"].update(
        status="verified_primary",
        screening_status="included_context",
        full_text_status="checked",
        checked_at=DATE,
        split_unit="not_applicable",
        cross_subject="not_applicable",
        external_validation="not_applicable",
        calibration="not_applicable",
        uncertainty="not_reported",
        exclusion_reason=None,
        notes="Full eLife Reviewed Preprint v1 checked. Publisher page uses version DOI 10.7554/eLife.97769.1; umbrella Crossref record 10.7554/eLife.97769 also exists. Data availability names neuPrint dataset MANC but does not fix S740's source export version.",
    )
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Article byline and citation metadata",
        "год": "Reviewed Preprint v1: 23 May 2024",
        "издание": "Article header: eLife 13:RP97769, Reviewed Preprint v1",
        "модальность": "Introduction; Results > Overview of the VNC connectome",
        "задача": "Abstract; Introduction",
        "метод": "Abstract; Methods > EM imaging, segmentation and synapse identification",
        "датасет": "Results > Overview of the VNC connectome; Data availability",
        "производительность": "Results > Table 1: reconstruction and completion counts",
        "кросс_субъект": "Methods > EM sample preparation: one male specimen",
        "ограничения": "Article header; Data availability; Discussion",
        "evidence.species": "Abstract and Methods: male Drosophila VNC",
        "evidence.population": "Methods > EM sample preparation: five-day-old male",
        "evidence.sample_size": "Methods > EM sample preparation: one male VNC specimen",
        "evidence.target_construct": "Abstract: connectome reconstruction",
        "evidence.target_label": "Abstract; Results > VNC connectome",
        "validation.split_unit": "Methods: no predictive training split",
        "validation.cross_subject": "Methods: one EM specimen",
        "validation.external_validation": "Results: anatomical resource, no external prediction test",
        "validation.calibration": "Methods: no probabilistic prediction task",
        "validation.uncertainty": "Results: no model uncertainty for transfer",
        "validation.notes": "Reviewed Preprint v1 header; Results; Methods; Data availability",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = "Checked in the primary eLife full text; source-release limits remain explicit."
        item["locators"] = [{"url": URL, "locator": section}]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
