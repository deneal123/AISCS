"""Populate the first relevance-5 review batch from checked primary sources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.core import load_json  # noqa: E402
from service.pipeline import atomic_write_json  # noqa: E402

DATA = ROOT / "data"
PATH = DATA / "curation" / "relevance-5" / "batches" / "batch-001.json"
CHECKED_AT = "2026-09-22"


def search(query: str, url: str, service: str, result: str) -> dict[str, str]:
    return {"service": service, "query": query, "url": url, "result": result}


def alias(source_id: str, canonical_id: str, searches: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "decision": "alias",
        "canonical_id": canonical_id,
        "reason": "confirmed_title_variant_of_same_primary_source",
        "checked_at": CHECKED_AT,
        "searches": searches,
        "claims": [],
        "notes": "Название, год, издание и уникальная метрика соответствуют одной публикации; отдельная версия не обнаружена.",
    }


def main() -> None:
    payload = load_json(PATH)
    zero_url = "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full"
    zero_searches = [
        search(
            '"Zero-shot multimodal pain estimation"',
            zero_url,
            "Frontiers",
            "Exact publisher article found; DOI and full text checked.",
        ),
        search(
            '"Zero-shot multimodal pain estimation" DOI',
            "https://doi.org/10.3389/frai.2026.1827727",
            "Crossref/DOI",
            "DOI resolves to the same publisher article.",
        ),
    ]
    subject_url = "https://www.sciencedirect.com/science/article/pii/S174680942601815X"
    subject_searches = [
        search(
            '"Deep Multi-Head attention network" "Subject-Incremental"',
            subject_url,
            "Elsevier",
            "Exact publisher article and full text metadata found.",
        ),
        search(
            '"10.1016/j.bspc.2026.111261"',
            "https://doi.org/10.1016/j.bspc.2026.111261",
            "Crossref/DOI",
            "DOI resolves to the same article.",
        ),
    ]
    painfusion_url = "https://www.sciencedirect.com/science/article/pii/S0925231225027389"
    painfusion_searches = [
        search(
            '"Multimodal pain assessment with transformers"',
            painfusion_url,
            "Elsevier",
            "Exact open publisher article found and content checked.",
        ),
        search(
            '"10.1016/j.neucom.2025.132066"',
            "https://doi.org/10.1016/j.neucom.2025.132066",
            "Crossref/DOI",
            "DOI resolves to the same article.",
        ),
    ]

    decisions: list[dict[str, Any]] = [
        {
            "source_id": "S149",
            "decision": "verified_primary",
            "checked_at": CHECKED_AT,
            "full_text_status": "checked",
            "searches": zero_searches,
            "updates": {
                "название": "Zero-shot multimodal pain estimation via synthetic pain simulation and domain-invariant learning",
                "авторы": "Oussama El Othmani; Sami Naouali",
                "год": 2026,
                "издание": "Frontiers in Artificial Intelligence 9:1827727",
                "модальность": "Видео; HRV/ECG; EDA; контекстные признаки",
                "задача": "Synthetic-source unsupervised domain adaptation for pain-intensity estimation",
                "метод": "Diffusion-based synthetic generation; multimodal transformer; domain adaptation",
                "датасет": "50,000 synthetic scenarios; UNBC-McMaster; BioVid; in-house neonatal cohort",
                "производительность": "UNBC MAE 0.89; BioVid accuracy 78.3%; neonatal accuracy 81.5%",
                "кросс_субъект": "Да, разбиения по субъектам; полностью независимый внешний центр отсутствует",
                "ограничения": "Ретроспективные наборы; real data used unlabeled for alignment; no fourth held-out external site; neonatal cohort is small.",
                "identifiers": {
                    "doi": "10.3389/frai.2026.1827727",
                    "exact_url": zero_url,
                },
                "provenance": {
                    "retrieved_at": CHECKED_AT,
                    "search_stream": "relevance-5/batch-001",
                    "query_or_seed": '"Zero-shot multimodal pain estimation"',
                    "iteration": 1,
                },
                "evidence": {
                    "species": "Homo sapiens and synthetic humans",
                    "population": "UNBC, BioVid, 15 neonates, synthetic demographic strata",
                    "subject_domain": "mixed",
                    "modalities": ["ecg", "eda", "metadata", "movement_pose", "video_face"],
                    "sample_size": "50,000 synthetic scenarios; UNBC 25 subjects; BioVid 87 subjects; 120 segments from 15 neonates",
                    "target_construct": "experimental_pain_class",
                    "target_label": "continuous 0-10 pain intensity / dataset-specific pain labels",
                    "access_status": "open",
                    "evidence_role": "method_baseline",
                },
                "validation": {
                    "split_unit": "participant",
                    "cross_subject": "yes",
                    "external_validation": "no",
                    "calibration": "yes",
                    "uncertainty": "yes",
                },
                "risk_flags": ["future_or_recent_record_requires_recheck", "synthetic_only"],
            },
            "claims": [
                {
                    "claim": "Synthetic-source domain adaptation can be evaluated on retrospective human pain benchmarks without labeled real target samples during training.",
                    "target_variable": "pain intensity",
                    "population_or_data": "UNBC-McMaster, BioVid, neonatal cohort",
                    "evidence": "Publisher full text reports MAE 0.89 on UNBC, 78.3% accuracy on BioVid and 81.5% on the neonatal cohort.",
                    "limitation": "All real benchmark data are retrospective and used at least unlabeled during alignment; no fully independent fourth site.",
                    "permitted_conclusion": "Feasibility on the tested datasets only; not clinical validation and not evidence for Drosophila-to-human transfer.",
                },
                {
                    "claim": "The imported 96% value describes this paper.",
                    "target_variable": "performance",
                    "population_or_data": "unspecified",
                    "evidence": "Unsupported; exact full text contains no matching headline 96% result.",
                    "limitation": "The original registry did not provide a locator.",
                    "permitted_conclusion": "Do not cite 96%; use the dataset-specific published metrics.",
                },
            ],
            "notes": "Primary article checked. The source calls the setup zero-shot in the qualified sense of zero labeled real target examples, not classical zero-shot learning.",
        },
        {
            "source_id": "S224",
            "decision": "verified_primary",
            "checked_at": CHECKED_AT,
            "full_text_status": "checked",
            "searches": [
                search(
                    "site:github.com/oussama123-ai/ZSL_MPE",
                    "https://github.com/oussama123-ai/ZSL_MPE",
                    "GitHub",
                    "Repository linked directly by the publisher article.",
                ),
                *zero_searches,
            ],
            "updates": {
                "название": "ZSL_MPE: code for Zero-shot multimodal pain estimation via synthetic pain simulation and domain-invariant learning",
                "авторы": "Oussama El Othmani; Sami Naouali",
                "год": 2026,
                "издание": "GitHub",
                "производительность": None,
                "identifiers": {"exact_url": "https://github.com/oussama123-ai/ZSL_MPE"},
                "provenance": {
                    "retrieved_at": CHECKED_AT,
                    "search_stream": "relevance-5/batch-001",
                    "query_or_seed": "site:github.com/oussama123-ai/ZSL_MPE",
                    "iteration": 1,
                },
                "evidence": {
                    "subject_domain": "simulation",
                    "modalities": ["ecg", "eda", "metadata", "movement_pose", "video_face"],
                    "target_construct": "not_applicable",
                    "evidence_role": "context_only",
                    "access_status": "open",
                },
                "validation": {
                    "split_unit": "not_applicable",
                    "cross_subject": "not_applicable",
                    "external_validation": "not_applicable",
                    "calibration": "not_applicable",
                    "uncertainty": "not_applicable",
                },
                "relations": [
                    {
                        "type": "code_for",
                        "target_id": "S149",
                        "external_id": None,
                        "note": "Repository linked from the publisher full text.",
                    }
                ],
                "risk_flags": ["future_or_recent_record_requires_recheck"],
            },
            "claims": [],
            "notes": "Code repository verified through the publisher's full-text link; retained separately and linked with code_for.",
        },
        {
            "source_id": "S039",
            "decision": "verified_primary",
            "checked_at": CHECKED_AT,
            "full_text_status": "checked",
            "searches": subject_searches,
            "updates": {
                "название": "Deep Multi-Head attention network with Subject-Incremental learning for Cross-Subject generalization in objective pain monitoring using multimodal physiological signals",
                "авторы": "Rakesh Chandra Joshi; Suman Kumar; Sujeet Kumar Singh Gautam; Malay Kishore Dutta",
                "год": 2026,
                "издание": "Biomedical Signal Processing and Control 128:111261",
                "модальность": "EDA; BVP; ECG; EMG; respiration",
                "задача": "Six-class participant-independent experimental pain recognition",
                "метод": "Subject-incremental multi-head attention and deep fusion with SHAP",
                "датасет": "PainMonit PMED",
                "производительность": "87.68% ± 0.41% mean participant-level accuracy across four subject-independent outer folds",
                "кросс_субъект": "Да, subject-wise four-fold outer cross-validation",
                "ограничения": "52 healthy participants under controlled thermal stimulation; no chronic-pain clinical validation.",
                "identifiers": {"doi": "10.1016/j.bspc.2026.111261", "exact_url": subject_url},
                "provenance": {
                    "retrieved_at": CHECKED_AT,
                    "search_stream": "relevance-5/batch-001",
                    "query_or_seed": '"Deep Multi-Head attention network" "Subject-Incremental"',
                    "iteration": 1,
                },
                "evidence": {
                    "species": "Homo sapiens",
                    "population": "52 healthy PMED participants exposed to graded thermal stimulation",
                    "subject_domain": "human_healthy",
                    "modalities": ["bvp_ppg", "ecg", "eda", "emg"],
                    "sample_size": 52,
                    "target_construct": "experimental_pain_class",
                    "target_label": "baseline, non-painful stimulation, and four graded pain levels",
                    "access_status": "open",
                    "evidence_role": "method_baseline",
                },
                "validation": {
                    "split_unit": "participant",
                    "cross_subject": "yes",
                    "external_validation": "no",
                    "calibration": "not_reported",
                    "uncertainty": "not_reported",
                },
                "risk_flags": ["future_or_recent_record_requires_recheck"],
            },
            "claims": [
                {
                    "claim": "The method reports 87.68% participant-level accuracy for six-class recognition.",
                    "target_variable": "experimental pain class",
                    "population_or_data": "PainMonit PMED, 52 healthy participants",
                    "evidence": "Elsevier full text reports 87.68% ± 0.41% across four subject-independent outer folds.",
                    "limitation": "Controlled thermal stimulation in healthy participants; no independent clinical cohort.",
                    "permitted_conclusion": "Cross-subject feasibility within PMED, not general clinical pain validity.",
                }
            ],
            "notes": "Primary publisher record and article text checked.",
        },
        {
            "source_id": "S036",
            "decision": "verified_primary",
            "checked_at": CHECKED_AT,
            "full_text_status": "checked",
            "searches": painfusion_searches,
            "updates": {
                "название": "Multimodal pain assessment with transformers",
                "авторы": "Manuel Benavent-Lledó; Maria Dolores Lopez-Valle; David Ortiz-Pérez; David Mulero-Pérez; José García-Rodríguez; Alexandra Psarrou",
                "год": 2026,
                "издание": "Neurocomputing 664:132066",
                "модальность": "Facial video; ECG; EMG; GSR/EDA",
                "задача": "Multimodal experimental pain classification",
                "метод": "CNN physiological encoder; frozen video transformer; transformer fusion",
                "датасет": "BioVid Heat Pain Database",
                "производительность": "35.40% accuracy on the reported BioVid multimodal task; >16 percentage-point improvement for biomedical signal processing",
                "кросс_субъект": None,
                "ограничения": "Experimental heat-pain benchmark; publisher text does not establish SCS/ECAP or clinical generalizability.",
                "identifiers": {"doi": "10.1016/j.neucom.2025.132066", "exact_url": painfusion_url},
                "provenance": {
                    "retrieved_at": CHECKED_AT,
                    "search_stream": "relevance-5/batch-001",
                    "query_or_seed": '"Multimodal pain assessment with transformers"',
                    "iteration": 1,
                },
                "evidence": {
                    "species": "Homo sapiens",
                    "population": "BioVid healthy participants under controlled heat stimulation",
                    "subject_domain": "human_healthy",
                    "modalities": ["ecg", "eda", "emg", "video_face"],
                    "sample_size": None,
                    "target_construct": "experimental_pain_class",
                    "target_label": "BioVid pain classes",
                    "access_status": "open",
                    "evidence_role": "method_baseline",
                },
                "validation": {
                    "split_unit": "not_reported",
                    "cross_subject": "not_reported",
                    "external_validation": "no",
                    "calibration": "not_reported",
                    "uncertainty": "not_reported",
                },
                "risk_flags": [
                    "future_or_recent_record_requires_recheck",
                    "missing_cross_subject_validation",
                ],
            },
            "claims": [
                {
                    "claim": "PainFusion+ reports 35.40% accuracy on its BioVid multimodal task.",
                    "target_variable": "experimental pain class",
                    "population_or_data": "BioVid",
                    "evidence": "The open Elsevier article states 35.40% accuracy and describes the multimodal transformer.",
                    "limitation": "The exact split unit is not recorded in this curation pass; BioVid is experimental heat pain.",
                    "permitted_conclusion": "Method baseline for experimental multimodal classification only.",
                }
            ],
            "notes": "Primary open publisher article checked.",
        },
    ]

    for source_id in ("S210", "S256", "S304", "S380"):
        decisions.append(alias(source_id, "S149", zero_searches))
    for source_id in (
        "S056",
        "S089",
        "S118",
        "S132",
        "S178",
        "S225",
        "S258",
        "S353",
        "S366",
        "S407",
    ):
        decisions.append(alias(source_id, "S039", subject_searches))
    for source_id in ("S053", "S085", "S128"):
        decisions.append(alias(source_id, "S036", painfusion_searches))

    order = {source_id: index for index, source_id in enumerate(payload["source_ids"])}
    payload["decisions"] = sorted(decisions, key=lambda item: order[item["source_id"]])
    payload["meta"]["status"] = "reviewed"
    payload["meta"]["reviewed_at"] = CHECKED_AT
    atomic_write_json(PATH, payload)


if __name__ == "__main__":
    main()
