"""Integrate the publisher-verified canine/human EEG transfer analogue."""

# ruff: noqa: E501 -- preserve exact primary-source descriptions and locators.

from __future__ import annotations

import json
from pathlib import Path

from service.completeness import completeness_summary, migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
PUBLISHER = "https://academic.oup.com/nsr/article/12/6/nwaf086/8052010"


def main() -> None:
    path = ROOT / "records.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    existing = next((source for source in payload["sources"] if source["id"] == "S796"), None)
    record = {
        "id": "S796",
        "название": "Canine EEG helps human: cross-species and cross-modality epileptic seizure detection via multi-space alignment",
        "авторы": "Ziwei Wang; Siyang Li; Dongrui Wu",
        "год": 2025,
        "издание": "National Science Review 12(6):nwaf086",
        "модальность": "Canine and human intracranial EEG; human scalp EEG",
        "задача": "Cross-species and cross-modality detection of ictal versus interictal EEG trials",
        "метод": "ResizeNet plus multi-space alignment of input, feature and output spaces; canine-to-human and human-to-canine transfer, with unsupervised and semi-supervised target-data scenarios",
        "датасет": "Kaggle canine and human iEEG; Freiburg human iEEG; CHSZ and NICU human scalp EEG. Four heterogeneous datasets, without one combined subject denominator.",
        "производительность": "Table 1: mean unsupervised MSA AUC 75.53% canine-to-human and 76.89% human-to-canine across four tasks. Tables 2-3 report semi-supervised results; the abstract's over-90% AUC refers to cases with limited labeled target data, not the unsupervised setting.",
        "кросс_субъект": "Unsupervised: source-species labels only, each target subject tested separately. Semi-supervised: 5-20% labeled trials per class from the same target subject used in training; remaining trials from that subject used for testing.",
        "релевантность": 3,
        "ограничения": "Seizure detection on dog/human EEG is a methodological analogue for cross-species signal transfer. It does not use a Drosophila connectome, graph-derived causal invariant, spinal ECAP, SCS treatment, or pain outcome. Semi-supervised target-subject trial results cannot be described as subject-disjoint zero-shot transfer.",
        "тип_источника": "метод",
        "identifiers": {
            "doi": "10.1093/nsr/nwaf086",
            "pmid": "40330047",
            "arxiv_id": "2412.17842",
            "patent_id": None,
            "dataset_id": None,
            "exact_url": PUBLISHER,
        },
        "provenance": {
            "import_source": "NS-05 primary publisher full text",
            "retrieved_at": DATE,
            "search_stream": "NS-05",
            "query_or_seed": "cross-species canine human EEG transfer multi-space alignment",
            "iteration": 4,
        },
        "evidence": {
            "species": "Canis familiaris; Homo sapiens",
            "population": "Canine and human EEG subjects across four public datasets; target subjects evaluated separately",
            "subject_domain": "mixed",
            "modalities": ["eeg"],
            "sample_size": None,
            "target_construct": "not_applicable",
            "target_label": "Ictal versus interictal EEG trials",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "screening_status": "included_context",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "trial",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": "Publisher full text checked: Results and Analysis > Dataset introduction, Transfer learning approaches, Tables 1-3. Unsupervised evaluation tests target subjects using only other-species labels; semi-supervised evaluation trains on 5-20% labeled trials of each same target subject. Neither scenario establishes Drosophila-to-ECAP/SCS translation.",
        },
        "relations": [],
        "risk_flags": ["animal_to_human_transfer_unvalidated"],
    }
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "название": "Article title",
        "авторы": "Article byline",
        "год": "Citation header; publication 4 March 2025",
        "издание": "Citation header: National Science Review 12(6):nwaf086",
        "модальность": "Abstract; Introduction; Figure 1 caption",
        "задача": "Abstract; Results and Analysis > Dataset introduction",
        "метод": "Results and Analysis > Transfer learning approaches; Methods",
        "датасет": "Results and Analysis > Dataset introduction; Table B1",
        "производительность": "Results and Analysis > Tables 1-3",
        "кросс_субъект": "Results and Analysis > Dataset introduction, unsupervised and semi-supervised scenarios",
        "ограничения": "Abstract; Results and Analysis > Dataset introduction; Tables 1-3",
        "evidence.species": "Abstract; Results and Analysis > Dataset introduction",
        "evidence.population": "Results and Analysis > Dataset introduction; Table B1",
        "evidence.sample_size": "Table B1: dataset-specific counts; no single combined denominator",
        "evidence.target_construct": "Abstract: seizure detection, outside the pain/SCS construct vocabulary",
        "evidence.target_label": "Results and Analysis > Dataset introduction: seizure and non-seizure clips",
        "validation.split_unit": "Results and Analysis > Dataset introduction: labeled trials per class",
        "validation.cross_subject": "Results and Analysis > Dataset introduction: target-subject trial reuse in semi-supervised setting",
        "validation.external_validation": "Results and Analysis > Dataset introduction; no independent SCS or ECAP cohort",
        "validation.calibration": "Results and Analysis > Tables 1-3: AUC, no probability calibration",
        "validation.uncertainty": "Results and Analysis > Tables 1-3: AUC variation, no predictive uncertainty model",
        "validation.notes": "Results and Analysis > Dataset introduction; Tables 1-3",
    }
    for field, locator in locators.items():
        if field not in record["field_resolution"]:
            continue
        record["field_resolution"][field]["locators"] = [{"url": PUBLISHER, "locator": locator}]
    record["field_resolution"]["evidence.sample_size"]["reason"] = (
        "Four heterogeneous datasets have dataset-specific counts, not one pooled subject denominator."
    )
    record["field_resolution"]["validation.cross_subject"]["reason"] = (
        "The two scenarios have different target-subject use; one aggregate cross-subject yes/no would mislead."
    )
    if existing is None:
        payload["sources"].append(record)
    elif existing != record:
        raise ValueError("S796 differs from prepared card; refusing to replace reviewed edits")
    payload["meta"]["records_count"] = len(payload["sources"])
    payload["meta"]["verified_primary_count"] = sum(
        source["validation"]["status"] == "verified_primary" for source in payload["sources"]
    )
    atomic_write_json(path, payload)

    cluster_path = ROOT / "clusters.json"
    clusters = json.loads(cluster_path.read_text(encoding="utf-8"))
    if "S796" not in clusters["unclustered_record_ids"]:
        clusters["unclustered_record_ids"].append("S796")
    clusters["unclustered_decisions"]["S796"] = {
        "decision": "no_cluster_applicable",
        "checked_at": DATE,
        "reason": "Dog/human seizure EEG transfer is relevant methodological prior art, but none of the current fly nociception, ECAP or SCS content clusters describes its evidence construct.",
    }
    clusters["meta"]["records_count"] = len(payload["sources"])
    clusters["meta"]["unclustered_records_count"] = len(clusters["unclustered_record_ids"])
    atomic_write_json(cluster_path, clusters)

    completeness_path = ROOT / "completeness-report.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness.update(completeness_summary(payload["sources"]))
    completeness.setdefault("meta", {})["generated_at"] = DATE
    atomic_write_json(completeness_path, completeness)

    search_path = ROOT / "search-protocol.json"
    search = json.loads(search_path.read_text(encoding="utf-8"))
    stream = next(item for item in search["search_streams"] if item["id"] == "NS-05")
    if "S796" not in stream["source_ids"]:
        stream["source_ids"].append("S796")
    stream["coverage_note"] += (
        " S796 is a verified canine/human seizure-EEG transfer analogue with distinct unsupervised "
        "and semi-supervised target-trial scenarios; it does not validate fly-to-ECAP/SCS transfer."
        if "S796 is a verified" not in stream["coverage_note"] else ""
    )
    atomic_write_json(search_path, search)

    matrix_path = ROOT / "evidence-matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    row = {
        "batch_id": "ns05-wang-cross-species-eeg-2026-09-25",
        "claim": "A canine/human EEG cross-species transfer method predates the proposed neural-signal transfer component.",
        "target_variable": "Ictal versus interictal EEG trial classification across species and EEG modalities",
        "population_or_data": "Canine iEEG and human iEEG/scalp EEG in Kaggle, Freiburg, CHSZ and NICU datasets",
        "source_ids": ["S796"],
        "verified_evidence": "The published study aligns input, feature and output spaces. Table 1 reports unsupervised cross-species AUC. Tables 2-3 report semi-supervised evaluations using 5-20% labeled trials per class from each same target subject.",
        "limitations": "No Drosophila connectome, causal-invariant test, spinal ECAP, SCS intervention or pain outcome. The semi-supervised result is not a subject-disjoint zero-shot transfer result.",
        "permitted_conclusion": "Use as cross-species EEG transfer prior art and method baseline only; retain the Drosophila-to-ECAP/SCS validation gap.",
        "locators": [
            {
                "source_id": "S796",
                "url": PUBLISHER,
                "locator": "Abstract; Results and Analysis > Dataset introduction and Transfer learning approaches; Tables 1-3",
            }
        ],
    }
    if not any(item["batch_id"] == row["batch_id"] for item in matrix["rows"]):
        matrix["rows"].append(row)
    atomic_write_json(matrix_path, matrix)
    print("Integrated S796 into canonical records, clusters, completeness, search and evidence matrix")


if __name__ == "__main__":
    main()
