"""Rebuild the working research JSON files from the immutable 2026-09-21 snapshot.

The script performs only evidence-preserving transformations:
- removes byte-for-byte-equivalent source records while retaining aliases;
- merges a small, explicit set of semantic duplicates verified against primary sources;
- replaces placeholder strings with null in fields where absence is meaningful;
- adds provenance, identifiers, evidence status, validation status and risk flags;
- repairs cluster references, representatives and counters;
- annotates ST resources and replaces a small set of verified generic links;
- writes a reproducible audit report and validation log.

It intentionally does not invent missing bibliographic metadata for unverified records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "data"
SNAPSHOT = ROOT / "archive" / "2026-09-21"
CHECKED_AT = "2026-09-21"

LEGACY_FIELDS = [
    "название",
    "авторы",
    "год",
    "издание",
    "модальность",
    "задача",
    "метод",
    "датасет",
    "производительность",
    "кросс_субъект",
    "релевантность",
    "ограничения",
    "тип_источника",
]

NULLABLE_PLACEHOLDER_FIELDS = {
    "авторы",
    "год",
    "издание",
    "модальность",
    "задача",
    "метод",
    "датасет",
    "производительность",
    "кросс_субъект",
    "ограничения",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def numeric_id(source_id: str) -> int:
    match = re.fullmatch(r"S(\d+)", source_id)
    return int(match.group(1)) if match else 10**9


def exact_key(record: dict[str, Any]) -> str:
    payload = {key: record.get(key) for key in LEGACY_FIELDS}
    # The legacy audit treated title capitalization as non-semantic. Keep that
    # behavior explicit instead of relying on PowerShell's case-insensitive grouping.
    if isinstance(payload.get("название"), str):
        payload["название"] = payload["название"].casefold()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_missing(record: dict[str, Any]) -> None:
    for key in NULLABLE_PLACEHOLDER_FIELDS:
        if record.get(key) == "Не указано":
            record[key] = None


def default_extensions(record: dict[str, Any]) -> None:
    record["identifiers"] = {
        "doi": None,
        "pmid": None,
        "arxiv_id": None,
        "patent_id": None,
        "dataset_id": None,
        "exact_url": None,
    }
    record["provenance"] = {
        "import_source": "archive/2026-09-21/records.json",
        "retrieved_at": None,
        "search_stream": None,
        "query_or_seed": None,
        "iteration": None,
    }
    record["evidence"] = {
        "species": None,
        "population": None,
        "sample_size": None,
        "target_construct": "unknown",
        "target_label": None,
        "access_status": "unknown",
        "evidence_role": "not_assigned",
    }
    record["validation"] = {
        "status": "unverified",
        "screening_status": "pending",
        "full_text_status": "not_checked",
        "checked_at": None,
        "notes": "Перенесено из необработанного реестра; требуется проверка по первичному источнику.",
    }
    record["risk_flags"] = build_risk_flags(record)


def build_risk_flags(record: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not record.get("авторы"):
        flags.append("missing_authors")
    if not record.get("год"):
        flags.append("missing_year")
    if not record.get("датасет"):
        flags.append("missing_dataset")
    if not record.get("производительность"):
        flags.append("missing_reported_metrics")
    if not record.get("кросс_субъект"):
        flags.append("missing_cross_subject_validation")
    if not any(record.get("identifiers", {}).values()):
        flags.append("missing_primary_identifier")
    source_type = str(record.get("тип_источника") or "").lower()
    venue = str(record.get("издание") or "").lower()
    title = str(record.get("название") or "").lower()
    if source_type == "препринт" or "arxiv" in venue or "biorxiv" in venue:
        flags.append("preprint")
    if source_type == "патент" or title.startswith("us20") or title.startswith("wo20"):
        flags.append("patent_not_empirical_evidence")
    if any(token in venue for token in ("yahoo", "coverage", "blog")) or "coverage" in title:
        flags.append("news_or_secondary_source")
    if any(token in title for token in ("synthetic", "simulation", "simulated", "doomfly")):
        flags.append("synthetic_only")
    if "drosophila" in title or "flywire" in title or "fly brain" in title:
        flags.append("animal_to_human_transfer_unvalidated")
    if "ecap" in title or "ecap" in str(record.get("модальность") or "").lower():
        flags.append("ecap_not_pain_measure")
    if record.get("год") == 2026:
        flags.append("future_or_recent_record_requires_recheck")
    return sorted(set(flags))


def verified_record(
    record: dict[str, Any],
    *,
    title: str,
    authors: str,
    year: int,
    venue: str,
    doi: str | None = None,
    pmid: str | None = None,
    dataset_id: str | None = None,
    exact_url: str,
    species: str | None,
    population: str | None,
    sample_size: str | int | None,
    target_construct: str,
    target_label: str | None,
    access_status: str,
    evidence_role: str,
    full_text_status: str,
    notes: str,
) -> None:
    record.update({"название": title, "авторы": authors, "год": year, "издание": venue})
    record["identifiers"].update(
        {
            "doi": doi,
            "pmid": pmid,
            "dataset_id": dataset_id,
            "exact_url": exact_url,
        }
    )
    record["provenance"].update(
        {
            "retrieved_at": CHECKED_AT,
            "search_stream": "G0_primary_source_validation",
            "query_or_seed": title,
            "iteration": "2026-09-21-pass-1",
        }
    )
    record["evidence"].update(
        {
            "species": species,
            "population": population,
            "sample_size": sample_size,
            "target_construct": target_construct,
            "target_label": target_label,
            "access_status": access_status,
            "evidence_role": evidence_role,
        }
    )
    record["validation"] = {
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": full_text_status,
        "checked_at": CHECKED_AT,
        "notes": notes,
    }
    record["risk_flags"] = build_risk_flags(record)


def make_new_record(source_id: str, **kwargs: Any) -> dict[str, Any]:
    record = {
        "id": source_id,
        "название": kwargs.pop("title"),
        "авторы": kwargs.pop("authors"),
        "год": kwargs.pop("year"),
        "издание": kwargs.pop("venue"),
        "модальность": kwargs.pop("modality"),
        "задача": kwargs.pop("task"),
        "метод": kwargs.pop("method"),
        "датасет": kwargs.pop("dataset"),
        "производительность": kwargs.pop("performance"),
        "кросс_субъект": kwargs.pop("cross_subject"),
        "релевантность": kwargs.pop("relevance"),
        "ограничения": kwargs.pop("limitations"),
        "тип_источника": kwargs.pop("source_type"),
    }
    default_extensions(record)
    verified_record(
        record,
        **kwargs,
        title=record["название"],
        authors=record["авторы"],
        year=record["год"],
        venue=record["издание"],
    )
    return record


def annotate_semantic_duplicates(records: list[dict[str, Any]]) -> list[list[str]]:
    normalized: dict[str, list[str]] = defaultdict(list)
    suffix = re.compile(r"\s*\((?:final|extended|final extended)\)\s*$", re.I)
    for record in records:
        title = suffix.sub("", record["название"]).strip().lower()
        title = re.sub(r"[^a-zа-я0-9]+", " ", title, flags=re.I).strip()
        normalized[title].append(record["id"])
    groups = [ids for ids in normalized.values() if len(ids) > 1]
    involved = {source_id for group in groups for source_id in group}
    for record in records:
        if record["id"] in involved and record["validation"]["status"] == "unverified":
            record["risk_flags"] = sorted(
                set(record["risk_flags"] + ["semantic_duplicate_pending"])
            )
    return sorted(groups, key=lambda group: numeric_id(group[0]))


def resolve_alias(source_id: str, aliases: dict[str, dict[str, str]]) -> str:
    seen: set[str] = set()
    current = source_id
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]["canonical_id"]
    return current


def apply_verified_overrides(records_by_id: dict[str, dict[str, Any]]) -> None:
    verified_record(
        records_by_id["S106"],
        title="FlyWire: Online community for whole-brain connectomics",
        authors="Dorkenwald, S. et al.",
        year=2022,
        venue="Nature Methods, 19(1), 119–128",
        doi="10.1038/s41592-021-01330-0",
        pmid="34949809",
        exact_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC8903166/",
        species="Drosophila melanogaster",
        population="female adult fly brain electron-microscopy volume",
        sample_size=None,
        target_construct="not_applicable",
        target_label=None,
        access_status="open",
        evidence_role="simulation_foundation",
        full_text_status="checked",
        notes="Проверена статья о платформе совместной реконструкции. Это не функциональная симуляция и не датасет боли.",
    )
    verified_record(
        records_by_id["S219"],
        title="FlyWire FAFB v783 adult female brain connectome",
        authors="Dorkenwald, S.; Matsliah, A.; Sterling, A. R. et al.; FlyWire Consortium",
        year=2024,
        venue="Nature 634, 124–138; Codex dataset v783",
        doi="10.1038/s41586-024-07558-y",
        dataset_id="FlyWire FAFB v783",
        exact_url="https://codex.flywire.ai/api/download?data_version=783",
        species="Drosophila melanogaster",
        population="adult female brain; central brain and optic lobes",
        sample_size="139255 neurons; 54.5 million chemical synapses",
        target_construct="not_applicable",
        target_label=None,
        access_status="registration_required",
        evidence_role="simulation_foundation",
        full_text_status="checked",
        notes="Коннектом мозга, а не тела, VNC или человеческого спинного мозга. Функциональная динамика не содержится в графе автоматически.",
    )
    records_by_id["S219"]["датасет"] = "FlyWire FAFB v783"
    records_by_id["S219"]["производительность"] = (
        "Ресурс: 139 255 нейронов и 54,5 млн химических синапсов"
    )
    records_by_id["S219"]["ограничения"] = (
        "Только мозг взрослой самки; анатомическая связность не задает физиологическую динамику и не моделирует VNC/SCS"
    )

    verified_record(
        records_by_id["S031"],
        title="Neural substrates of cold nociception in Drosophila larva",
        authors="Patel, A. A.; Cardona, A.; Cox, D. N.",
        year=2025,
        venue="eLife 12:RP91582",
        doi="10.7554/eLife.91582",
        pmid="40512662",
        exact_url="https://pubmed.ncbi.nlm.nih.gov/40512662/",
        species="Drosophila melanogaster",
        population="larvae",
        sample_size=None,
        target_construct="nociceptive_response",
        target_label="cold-evoked contraction and neural/calcium responses",
        access_status="open",
        evidence_role="simulation_foundation",
        full_text_status="checked",
        notes="Функционально исследует холодовую ноцицепцию личинки; не подтверждает субъективную боль человека или перенос на SCS.",
    )
    verified_record(
        records_by_id["S029"],
        title="Ascending nociceptive pathways drive rapid escape and sustained avoidance in adult Drosophila",
        authors="Jones, J. M.; Sustar, A.; Mamiya, A. et al.",
        year=2025,
        venue="bioRxiv preprint",
        doi="10.1101/2025.10.28.684868",
        pmid="41280033",
        exact_url="https://pubmed.ncbi.nlm.nih.gov/41280033/",
        species="Drosophila melanogaster",
        population="adult flies",
        sample_size=None,
        target_construct="nociceptive_response",
        target_label="escape and sustained avoidance after noxious stimulation",
        access_status="open",
        evidence_role="simulation_foundation",
        full_text_status="checked",
        notes="Препринт, не прошедший журнальное рецензирование на дату проверки. Поддерживает модель ноцицепции, но не человеческой боли.",
    )
    records_by_id["S029"]["тип_источника"] = "препринт"
    records_by_id["S029"]["risk_flags"] = build_risk_flags(records_by_id["S029"])

    verified_record(
        records_by_id["S280"],
        title="BioVid Heat Pain Database",
        authors="Walter, S.; Gruss, S.; Ehleiter, H. et al.",
        year=2013,
        venue="Official database page; Cyberworlds 2013 descriptor",
        dataset_id="BioVid Heat Pain Database",
        exact_url="https://www.nit.ovgu.de/BioVid.html",
        species="Homo sapiens",
        population="healthy adults exposed to calibrated experimental heat",
        sample_size="90 recruited; 87 in Part A",
        target_construct="experimental_pain_class",
        target_label="individualized heat-stimulus levels; pain-related responses",
        access_status="agreement_required",
        evidence_role="human_validation",
        full_text_status="checked",
        notes="Part A: video, GSR/EDA, ECG and trapezius EMG; non-commercial research access requires institutional agreement.",
    )
    records_by_id["S280"].update(
        {
            "модальность": "Видео, GSR/EDA, ECG, EMG",
            "задача": "Оценка реакции на индивидуально калиброванную экспериментальную тепловую стимуляцию",
            "метод": "Мультимодальный набор данных",
            "датасет": "BioVid Heat Pain Database, Parts A–E",
            "производительность": "Не применимо: описание набора данных",
            "кросс_субъект": "Рекомендуется LOSO; фиксировать точный состав участников",
            "ограничения": "Экспериментальная острая боль у здоровых взрослых; доступ по соглашению; не SCS/ECAP",
            "тип_источника": "датасет",
        }
    )
    records_by_id["S280"]["risk_flags"] = build_risk_flags(records_by_id["S280"])

    verified_record(
        records_by_id["S291"],
        title="AI4PAIN Grand Challenge 2024 dataset",
        authors="Fernandez-Rojas, R.; Joseph, C.; Hirachan, N. et al.",
        year=2024,
        venue="ACIIW 2024 / official challenge",
        dataset_id="AI4PAIN 2024",
        exact_url="https://sites.google.com/view/ai4pain/challenge-details",
        species="Homo sapiens",
        population="healthy volunteers under controlled painful stimulation",
        sample_size="65 participants: 41 train, 12 validation, 12 test",
        target_construct="experimental_pain_class",
        target_label="No Pain / Low Pain / High Pain",
        access_status="registration_required",
        evidence_role="human_validation",
        full_text_status="checked",
        notes="Подтверждены fNIRS и facial video. Физиологические EDA/BVP/RESP/SpO2 не подтверждены для версии challenge 2024 и исключены из описания.",
    )
    records_by_id["S291"].update(
        {
            "модальность": "fNIRS и видео лица",
            "задача": "Трехклассовая оценка экспериментально вызванной боли",
            "метод": "Grand Challenge dataset and fixed test protocol",
            "датасет": "AI4PAIN 2024",
            "производительность": "Официальный baseline: 43,3% accuracy; лучший результат challenge: до 51,3%",
            "кросс_субъект": "Фиксированные непересекающиеся train/validation/test по участникам",
            "ограничения": "Экспериментальная боль у здоровых участников; метки теста закрыты; не SCS/ECAP",
            "тип_источника": "датасет",
        }
    )
    records_by_id["S291"]["risk_flags"] = build_risk_flags(records_by_id["S291"])

    verified_record(
        records_by_id["S105"],
        title="Feature extraction and prediction of spinal cord stimulation evoked compound action potentials in humans",
        authors="König, S.; Ramadan, A.; Sullivan, D. et al.",
        year=2025,
        venue="Journal of Neural Engineering 22(2)",
        doi="10.1088/1741-2552/adbfbe",
        pmid="40073452",
        exact_url="https://pubmed.ncbi.nlm.nih.gov/40073452/",
        species="Homo sapiens",
        population="8 participants with chronic pain during externalized SCS trial",
        sample_size=8,
        target_construct="ecap_neural_recruitment",
        target_label="ECAP/non-ECAP/artifact and ECAP waveform features",
        access_status="open",
        evidence_role="scs_ecap_validation",
        full_text_status="checked",
        notes="Проверена обработка ECAP и межиндивидуальная вариабельность; исследование не является моделью прямого измерения боли.",
    )
    records_by_id["S105"]["risk_flags"] = build_risk_flags(records_by_id["S105"])

    verified_record(
        records_by_id["S159"],
        title="Biphasic Electrostimulation Artifact Model for ECAP Extraction in Spinal Cord Stimulation",
        authors="Zhang, H.; Luo, X.; Ma, B. et al.",
        year=2026,
        venue="IEEE Transactions on Neural Systems and Rehabilitation Engineering 34, 880–893",
        doi="10.1109/TNSRE.2026.3658636",
        pmid="41605141",
        exact_url="https://doi.org/10.1109/TNSRE.2026.3658636",
        species="Homo sapiens",
        population="two SCS patients; longitudinal clinical recordings",
        sample_size="2 patients; 208336 retained signals under 900 stimulation settings",
        target_construct="technical_signal_quality",
        target_label="stimulation artifact removal and ECAP extraction",
        access_status="open",
        evidence_role="scs_ecap_validation",
        full_text_status="checked",
        notes="Техническая работа по удалению артефакта и извлечению ECAP; не доказательство оценки боли или ответа на SCS.",
    )
    records_by_id["S159"]["risk_flags"] = build_risk_flags(records_by_id["S159"])


def build_new_verified_records() -> list[dict[str, Any]]:
    painmonit = make_new_record(
        "S730",
        title="The PainMonit Database: An Experimental and Clinical Physiological Signal Dataset for Automated Pain Recognition",
        authors="Gouverneur, P.; Badura, A.; Li, F. et al.",
        year=2024,
        venue="Scientific Data 11, 1051",
        modality="BVP, EDA, temperature, ECG, EMG, IBI, HR, respiration; clinical part also grip",
        task="Experimental and clinical pain assessment with stimulus and self-report labels",
        method="Open multimodal physiological dataset",
        dataset="PainMonit Experimental Dataset and PainMonit Clinical Dataset",
        performance="Not applicable: dataset descriptor",
        cross_subject="Participant identifiers are available for subject-wise splits",
        relevance=5,
        limitations="PMED and PMCD have different populations, elicitation and labels; they must not be pooled without domain-aware analysis",
        source_type="датасет",
        doi="10.1038/s41597-024-03878-w",
        dataset_id="10.6084/m9.figshare.26965159.v3",
        exact_url="https://figshare.com/articles/dataset/The_PainMonit_Database_An_Experimental_and_Clinical_Physiological_Signal_Dataset_for_Automated_Pain_Recognition/26965159",
        species="Homo sapiens",
        population="55 healthy participants in PMED; 49 physiotherapy patients in PMCD",
        sample_size="104 participants total",
        target_construct="self_reported_pain",
        target_label="stimulus intensity and/or self-reported VAS/NRS depending on subset",
        access_status="open",
        evidence_role="human_validation",
        full_text_status="checked",
        notes="Проверены статья Scientific Data, Figshare v3 и официальный кодовый репозиторий.",
    )
    neuromech = make_new_record(
        "S731",
        title="NeuroMechFly v2: simulating embodied sensorimotor control in adult Drosophila",
        authors="Wang-Chen, S.; Stimpfling, V. A.; Özdil, P. G. et al.",
        year=2024,
        venue="Nature Methods",
        modality="Biomechanics, proprioception, vision, olfaction, locomotion",
        task="Embodied sensorimotor simulation of adult Drosophila",
        method="MuJoCo-based neuromechanical model exposed through FlyGym",
        dataset="NeuroMechFly v2 / FlyGym",
        performance="Not a pain or nociception benchmark",
        cross_subject="Not applicable; model variability must be introduced explicitly",
        relevance=5,
        limitations="Does not provide a nociceptive circuit, subjective pain labels, ECAP measurement model or human SCS mapping out of the box",
        source_type="фундаментальные_модели",
        doi="10.1038/s41592-024-02497-y",
        dataset_id="10.5281/zenodo.12973000",
        exact_url="https://flygym.readthedocs.io/latest/index.html",
        species="Drosophila melanogaster",
        population="adult female fly biomechanical digital twin",
        sample_size=None,
        target_construct="not_applicable",
        target_label=None,
        access_status="open",
        evidence_role="simulation_foundation",
        full_text_status="checked",
        notes="Подтверждены официальный пакет FlyGym, документация, Apache-2.0 code availability and frozen Zenodo snapshot.",
    )
    return [painmonit, neuromech]


def rebuild_records(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, Any]]:
    sources = deepcopy(raw["sources"])
    exact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        exact_groups[exact_key(source)].append(source)

    aliases: dict[str, dict[str, str]] = {}
    kept: list[dict[str, Any]] = []
    for group in exact_groups.values():
        group.sort(key=lambda record: numeric_id(record["id"]))
        canonical = group[0]
        kept.append(canonical)
        for duplicate in group[1:]:
            aliases[duplicate["id"]] = {
                "canonical_id": canonical["id"],
                "reason": "exact_duplicate_except_id",
            }

    semantic_aliases = {
        # Verified representations of the same publication or dataset.
        "S063": "S031",
        "S093": "S031",
        "S135": "S031",
        "S156": "S031",
        "S197": "S031",
        "S064": "S029",
        "S091": "S029",
        "S134": "S029",
        "S151": "S029",
        "S196": "S029",
        "S166": "S106",
        "S218": "S106",
        "S251": "S219",
        "S305": "S280",
        "S326": "S280",
        "S341": "S280",
        "S382": "S280",
        "S301": "S291",
        "S325": "S291",
        "S340": "S291",
        "S383": "S291",
    }
    for alias, canonical in semantic_aliases.items():
        aliases[alias] = {
            "canonical_id": canonical,
            "reason": "verified_semantic_duplicate_or_version",
        }

    # Collapse aliases that pointed to a record later merged semantically.
    for alias in list(aliases):
        aliases[alias]["canonical_id"] = resolve_alias(aliases[alias]["canonical_id"], aliases)

    canonical_ids = {resolve_alias(record["id"], aliases) for record in kept}
    kept = [record for record in kept if record["id"] in canonical_ids]

    for record in kept:
        normalize_missing(record)
        default_extensions(record)

    records_by_id = {record["id"]: record for record in kept}
    apply_verified_overrides(records_by_id)
    kept.extend(build_new_verified_records())
    kept.sort(key=lambda record: numeric_id(record["id"]))

    pending_semantic_groups = annotate_semantic_duplicates(kept)

    output = {
        "meta": {
            "schema_version": "1.1.0",
            "version": "structural_cleanup_and_primary_validation_pass_1",
            "language": "ru",
            "source_snapshot": "archive/2026-09-21/records.json",
            "total_sources_processed_claimed_by_legacy": raw["meta"].get("total_sources_processed"),
            "records_count": len(kept),
            "verified_primary_count": sum(
                record["validation"]["status"] == "verified_primary" for record in kept
            ),
            "unverified_count": sum(
                record["validation"]["status"] == "unverified" for record in kept
            ),
            "aliases_count": len(aliases),
            "validation_status": "partial; structural cleanup complete, full bibliographic validation pending",
            "updated_at": CHECKED_AT,
        },
        "sources": kept,
    }
    stats = {
        "legacy_records": len(sources),
        "canonical_records": len(kept),
        "aliases": len(aliases),
        "exact_duplicate_groups": sum(len(group) > 1 for group in exact_groups.values()),
        "exact_redundant_records": sum(max(0, len(group) - 1) for group in exact_groups.values()),
        "pending_semantic_duplicate_groups": pending_semantic_groups,
    }
    return output, aliases, stats


def choose_representative(
    member_ids: list[str], records_by_id: dict[str, dict[str, Any]]
) -> str | None:
    if not member_ids:
        return None
    return sorted(
        member_ids,
        key=lambda source_id: (
            -int(records_by_id[source_id].get("релевантность", 0)),
            numeric_id(source_id),
        ),
    )[0]


def rebuild_clusters(
    raw: dict[str, Any],
    records: dict[str, Any],
    aliases: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    records_by_id = {record["id"]: record for record in records["sources"]}
    valid_ids = set(records_by_id)
    removed_missing: dict[str, list[str]] = {}
    clusters: list[dict[str, Any]] = []
    retired_clusters: list[dict[str, Any]] = []

    for raw_cluster in raw["clusters"]:
        cluster = deepcopy(raw_cluster)
        cleaned: list[str] = []
        missing: list[str] = []
        for source_id in cluster.get("состав_кластера", []):
            canonical = resolve_alias(source_id, aliases)
            if canonical in valid_ids:
                if canonical not in cleaned:
                    cleaned.append(canonical)
            else:
                missing.append(source_id)
        cleaned.sort(key=numeric_id)
        if missing:
            removed_missing[cluster["id"]] = sorted(set(missing), key=numeric_id)

        representative_id = resolve_alias(cluster.get("представитель", {}).get("id", ""), aliases)
        if representative_id not in cleaned:
            representative_id = choose_representative(cleaned, records_by_id)
        if not cleaned:
            retired_clusters.append(
                {
                    "id": cluster["id"],
                    "тема": cluster["тема"],
                    "reason": "all_legacy_member_ids_missing_from_canonical_records",
                    "original_member_ids": cluster.get("состав_кластера", []),
                }
            )
            continue

        cluster["состав_кластера"] = cleaned
        cluster["записей"] = len(cleaned)
        cluster["представитель"] = (
            records_by_id.get(representative_id) if representative_id else None
        )
        cluster["validation"] = {
            "status": "structurally_valid",
            "checked_at": CHECKED_AT,
            "content_validation": "pending",
        }
        clusters.append(cluster)

    referenced = [source_id for cluster in clusters for source_id in cluster["состав_кластера"]]
    unclustered = sorted(valid_ids - set(referenced), key=numeric_id)
    multi_membership = {
        source_id: count
        for source_id, count in sorted(
            Counter(referenced).items(), key=lambda item: numeric_id(item[0])
        )
        if count > 1
    }
    output = {
        "meta": {
            "schema_version": "1.1.0",
            "version": "structural_cleanup_pass_1",
            "language": "ru",
            "source_snapshot": "archive/2026-09-21/clusters.json",
            "records_count": len(records_by_id),
            "clusters_count": len(clusters),
            "retired_clusters_count": len(retired_clusters),
            "cluster_references_count": len(referenced),
            "unique_clustered_records_count": len(set(referenced)),
            "unclustered_records_count": len(unclustered),
            "multiple_membership_records_count": len(multi_membership),
            "validation_status": "structurally valid; thematic review pending",
            "updated_at": CHECKED_AT,
        },
        "clusters": clusters,
        "retired_clusters": retired_clusters,
        "unclustered_record_ids": unclustered,
        "multiple_membership": multi_membership,
    }
    stats = {
        "removed_missing_references": removed_missing,
        "removed_missing_references_count": len(
            {source_id for ids in removed_missing.values() for source_id in ids}
        ),
        "retired_empty_clusters": [cluster["id"] for cluster in retired_clusters],
        "unclustered_records": unclustered,
        "multiple_membership": multi_membership,
    }
    return output, stats


VERIFIED_ST_RESOURCES = {
    "FlyWire Codex (API для скачивания)": {
        "url": "https://codex.flywire.ai/api/download?data_version=783",
        "status": "verified_primary",
        "note": "FAFB v783: мозг взрослой самки; 139255 нейронов. Для CNS/VNC использовать отдельные наборы.",
    },
    "FlyWire v783 (browsable)": {
        "url": "https://codex.flywire.ai/?dataset=fafb",
        "status": "verified_primary",
        "note": "Интерактивный просмотр FAFB; не функциональный симулятор.",
    },
    "NeuroMechFly v2 / FlyGym": {
        "url": "https://flygym.readthedocs.io/latest/index.html",
        "status": "verified_primary",
        "note": "Официальная документация embodied-модели; nociception/ECAP не реализованы автоматически.",
    },
    "NeuroMechFly v2 Docs": {
        "url": "https://flygym.readthedocs.io/latest/index.html",
        "status": "verified_primary",
        "note": "Официальная документация FlyGym.",
    },
    "philshiu/Drosophila_brain_model": {
        "url": "https://github.com/philshiu/Drosophila_brain_model",
        "status": "verified_primary",
        "note": "Открытая LIF-модель; требует отдельной проверки соответствия версии коннектома и воспроизводимости.",
    },
    "BioVid HeatPain Database": {
        "url": "https://www.nit.ovgu.de/BioVid.html",
        "status": "verified_primary",
        "note": "Доступ для некоммерческих исследований по соглашению; Part A содержит 87 участников.",
    },
    "AI4Pain Grand Challenge": {
        "url": "https://sites.google.com/view/ai4pain/challenge-details",
        "status": "verified_primary",
        "note": "65 участников, fNIRS+video, фиксированные train/validation/test.",
    },
    "PainMonit Dataset": {
        "url": "https://figshare.com/articles/dataset/The_PainMonit_Database_An_Experimental_and_Clinical_Physiological_Signal_Dataset_for_Automated_Pain_Recognition/26965159",
        "status": "verified_primary",
        "note": "Figshare v3; PMED 55 и PMCD 49 участников; DOI 10.1038/s41597-024-03878-w.",
    },
    "Ascending nociceptive pathways (bioRxiv 2025)": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41280033/",
        "status": "verified_primary",
        "note": "Препринт; DOI 10.1101/2025.10.28.684868. Не считать рецензированной журнальной статьей.",
    },
    "data_CL_SCS (Figshare)": {
        "url": None,
        "status": "unverified",
        "note": "Точная запись Figshare по указанному названию не подтверждена; общая ссылка удалена из рабочего поля.",
    },
    "ECAP + conductivity data (Figshare)": {
        "url": None,
        "status": "unverified",
        "note": "Точная запись Figshare и состав данных не подтверждены; не использовать как доступный датасет.",
    },
    "Epidural spinal recordings (Newcastle)": {
        "url": None,
        "status": "partially_verified",
        "note": "Подтверждена публикация о preclinical epidural recordings, но открытый датасет по указанной ссылке не подтвержден.",
    },
}


def rebuild_st(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    output = deepcopy(raw)
    output["meta"]["исходная_тема"] = output["meta"]["тема"]
    output["meta"]["тема"] = (
        "Синтетическое мультимодальное предобучение на коннектомной модели Drosophila "
        "для проверки переноса на межсубъектную оценку болевого состояния и условного прогноза ответа на SCS"
    )
    output["meta"]["версия"] = "1.1.0-validated-pass-1"
    output["meta"]["дата_валидации"] = CHECKED_AT
    output["meta"]["статус_валидации"] = (
        "частично проверено; непроверенные ресурсы не являются доказательной базой"
    )

    resources: list[dict[str, Any]] = []
    generic_pattern = re.compile(r"^https?://[^/]+/?$")
    for category in output["categories"]:
        for subcategory in category.get("подкатегории", []):
            for resource in subcategory.get("ресурсы", []):
                resources.append(resource)
                name = resource.get("название")
                original_url = resource.get("ссылка")
                if name in VERIFIED_ST_RESOURCES:
                    verified = VERIFIED_ST_RESOURCES[name]
                    if original_url != verified["url"]:
                        resource["исходная_ссылка"] = original_url
                    resource["ссылка"] = verified["url"]
                    resource["статус_валидации"] = verified["status"]
                    resource["проверено"] = CHECKED_AT
                    resource["примечание_валидации"] = verified["note"]
                elif original_url and generic_pattern.match(original_url):
                    resource["исходная_ссылка"] = original_url
                    resource["ссылка"] = None
                    resource["статус_валидации"] = "needs_exact_url"
                    resource["проверено"] = None
                    resource["примечание_валидации"] = (
                        "Общая страница домена не подтверждает конкретный ресурс; требуется точная первичная ссылка."
                    )
                elif original_url:
                    resource["статус_валидации"] = "url_present_content_not_checked"
                    resource["проверено"] = None
                    resource["примечание_валидации"] = (
                        "Точный URL присутствует, содержание еще не проверено."
                    )
                else:
                    resource["статус_валидации"] = "unverified"
                    resource["проверено"] = None
                    resource["примечание_валидации"] = "Нет проверяемой ссылки."

    counts = Counter(resource["статус_валидации"] for resource in resources)
    output["meta"]["всего_ресурсов"] = len(resources)
    output["meta"]["проверено_по_первичному_источнику"] = counts["verified_primary"]
    output["meta"]["требуют_точной_ссылки"] = counts["needs_exact_url"]
    output["meta"]["не_подтверждено"] = counts["unverified"]
    output["notes"] = [
        "BioVid требует соглашения для некоммерческого исследования; AI4PAIN использует регистрацию/EULA; PainMonit доступен через Figshare.",
        "На первом проходе не подтвержден открытый человеческий набор, одновременно содержащий SCS/ECAP и клинический исход боли.",
        "FlyWire FAFB v783 описывает мозг взрослой самки, а не VNC/тело; анатомическая связность не задает физиологическую динамику.",
        "NeuroMechFly/FlyGym является embodied sensorimotor framework, но не содержит готовой модели ноцицепции, ECAP или человеческой SCS.",
        "Непроверенные ресурсы и общие доменные ссылки нельзя использовать в ИПР, статье или заявке на новизну до валидации.",
    ]
    return output, {
        "resource_status_counts": dict(sorted(counts.items())),
        "resource_count": len(resources),
    }


def build_validation_log() -> dict[str, Any]:
    return {
        "meta": {
            "version": "1.0.0",
            "checked_at": CHECKED_AT,
            "scope": "priority sources for dissertation concept and dataset feasibility",
            "status": "partial",
        },
        "checks": [
            {
                "subject": "FlyWire FAFB v783",
                "status": "verified_primary",
                "primary_url": "https://www.nature.com/articles/s41586-024-07558-y",
                "data_url": "https://codex.flywire.ai/api/download?data_version=783",
                "verified_claims": [
                    "139255 neurons",
                    "54.5 million chemical synapses",
                    "adult female brain",
                ],
                "limitations": [
                    "brain only",
                    "not VNC or body",
                    "connectivity is not a physiological simulation",
                ],
            },
            {
                "subject": "NeuroMechFly v2 / FlyGym",
                "status": "verified_primary",
                "primary_url": "https://www.nature.com/articles/s41592-024-02497-y",
                "data_url": "https://flygym.readthedocs.io/latest/index.html",
                "verified_claims": [
                    "MuJoCo-based embodied adult Drosophila model",
                    "open FlyGym package",
                ],
                "limitations": [
                    "no ready-made nociception model",
                    "no ECAP observation model",
                    "no human SCS mapping",
                ],
            },
            {
                "subject": "BioVid Heat Pain Database",
                "status": "verified_primary",
                "primary_url": "https://www.nit.ovgu.de/BioVid.html",
                "verified_claims": [
                    "90 recruited",
                    "87 subjects in Part A",
                    "video, GSR, ECG, EMG",
                ],
                "limitations": [
                    "experimental heat pain",
                    "healthy participants",
                    "agreement required",
                    "not SCS/ECAP",
                ],
            },
            {
                "subject": "AI4PAIN 2024",
                "status": "verified_primary",
                "primary_url": "https://sites.google.com/view/ai4pain/challenge-details",
                "verified_claims": [
                    "65 participants",
                    "fNIRS and facial video",
                    "41/12/12 participant split",
                ],
                "limitations": ["experimental pain classes", "not SCS/ECAP"],
            },
            {
                "subject": "PainMonit",
                "status": "verified_primary",
                "primary_url": "https://doi.org/10.1038/s41597-024-03878-w",
                "data_url": "https://figshare.com/articles/dataset/The_PainMonit_Database_An_Experimental_and_Clinical_Physiological_Signal_Dataset_for_Automated_Pain_Recognition/26965159",
                "verified_claims": [
                    "55 PMED participants",
                    "49 PMCD participants",
                    "multimodal physiology",
                    "self-report labels",
                ],
                "limitations": ["PMED and PMCD are distinct domains", "not SCS/ECAP"],
            },
            {
                "subject": "adult Drosophila ascending nociception pathways",
                "status": "verified_primary",
                "primary_url": "https://pubmed.ncbi.nlm.nih.gov/41280033/",
                "verified_claims": [
                    "thermal nociceptive response",
                    "escape",
                    "sustained avoidance",
                ],
                "limitations": [
                    "preprint",
                    "nociception is not human subjective pain",
                    "not an SCS model",
                ],
            },
            {
                "subject": "larval cold nociception circuitry",
                "status": "verified_primary",
                "primary_url": "https://pubmed.ncbi.nlm.nih.gov/40512662/",
                "verified_claims": [
                    "cold-evoked neural and behavioral responses",
                    "functionally tested larval circuitry",
                ],
                "limitations": ["larval model", "not human subjective pain", "not SCS/ECAP"],
            },
            {
                "subject": "human SCS ECAP feature extraction",
                "status": "verified_primary",
                "primary_url": "https://pubmed.ncbi.nlm.nih.gov/40073452/",
                "verified_claims": [
                    "8 chronic-pain participants",
                    "ECAP/non-ECAP/artifact classification",
                    "inter-individual variability",
                ],
                "limitations": ["ECAP processing, not direct pain measurement", "small cohort"],
            },
            {
                "subject": "open human SCS/ECAP dataset with pain outcomes",
                "status": "not_confirmed",
                "primary_url": None,
                "verified_claims": [],
                "limitations": [
                    "generic Figshare/Newcastle links in ST did not establish an accessible linked dataset"
                ],
            },
        ],
    }


def build_payloads() -> dict[str, Any]:
    raw_records = load_json(SNAPSHOT / "records.json")
    raw_clusters = load_json(SNAPSHOT / "clusters.json")
    raw_st = load_json(SNAPSHOT / "ST.json")

    records, aliases, record_stats = rebuild_records(raw_records)
    clusters, cluster_stats = rebuild_clusters(raw_clusters, records, aliases)
    st, st_stats = rebuild_st(raw_st)

    alias_payload = {
        "meta": {
            "version": "1.0.0",
            "source_snapshot": "archive/2026-09-21/records.json",
            "aliases_count": len(aliases),
            "updated_at": CHECKED_AT,
        },
        "aliases": dict(sorted(aliases.items(), key=lambda item: numeric_id(item[0]))),
    }
    audit_report = {
        "meta": {
            "version": "1.0.0",
            "generated_at": CHECKED_AT,
            "scope": "structural cleanup and priority-source validation pass 1",
            "gate": "G0_REVISE",
        },
        "snapshot_hashes": {
            name: sha256(SNAPSHOT / name) for name in ("records.json", "clusters.json", "ST.json")
        },
        "records": record_stats,
        "clusters": cluster_stats,
        "ST": st_stats,
        "remaining_blockers": [
            "Most records still lack a verified primary identifier and provenance.",
            "Semantic duplicate groups remain pending where identity cannot be proved from current metadata.",
            "Thematic cluster membership has not yet been reviewed by a domain expert.",
            "No open human dataset linking SCS/ECAP to a clinical pain outcome was confirmed in pass 1.",
            "No evidence currently validates transfer from a Drosophila simulator to human pain or SCS outcomes.",
        ],
    }

    return {
        "records.json": records,
        "aliases.json": alias_payload,
        "clusters.json": clusters,
        "ST.json": st,
        "validation-log.json": build_validation_log(),
        "audit-report.json": audit_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce the first migration from the immutable 2026-09-21 snapshot."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="build deterministically in memory and report hashes without writing files",
    )
    mode.add_argument(
        "--output-dir",
        type=Path,
        help="write the reproduced first-migration artifacts to a separate directory",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="explicitly overwrite the current canonical data (normally unsafe)",
    )
    args = parser.parse_args()
    payloads = build_payloads()
    serialized = {
        name: (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        for name, payload in payloads.items()
    }
    if args.check:
        print(
            json.dumps(
                {
                    "ok": True,
                    "writes": False,
                    "source_snapshot": str(SNAPSHOT),
                    "sha256": {
                        name: hashlib.sha256(content).hexdigest().upper()
                        for name, content in serialized.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    output_dir = ROOT if args.apply else args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        write_json(output_dir / name, payload)


if __name__ == "__main__":
    main()
