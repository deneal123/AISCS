"""One-way, conservative migration of the canonical corpus to schema 1.2."""

from __future__ import annotations

import argparse
import re
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from service.core import load_json  # noqa: E402
from service.pipeline import atomic_write_json  # noqa: E402

DATA = RESEARCH_ROOT / "data"


MODALITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eda", ("eda", "gsr", "электродерм", "кожно-галван")),
    ("eeg", ("eeg", "ээг")),
    ("ecg", ("ecg", "экг", "hrv")),
    ("emg", ("emg", "эмг")),
    ("bvp_ppg", ("bvp", "ppg", "фпг")),
    ("fnirs", ("fnirs",)),
    ("meg", ("meg", "мэг")),
    ("video_face", ("video", "видео", "face", "facial", "лиц")),
    ("thermal_video", ("thermal", "терм")),
    ("audio", ("audio", "аудио", "voice", "голос")),
    ("movement_pose", ("movement", "motion", "pose", "движ", "поза")),
    ("ecap", ("ecap", "compound action potential")),
    ("neural_activity", ("neural activity", "нейронн", "spike")),
    ("connectome", ("connectom", "коннектом")),
    ("behavior", ("behavior", "поведен")),
    ("clinical_outcome", ("clinical outcome", "клиническ", "responder")),
    ("simulation_state", ("simulation", "симуляц", "synthetic state")),
)


def normalized_modalities(record: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(record.get(field) or "") for field in ("модальность", "задача", "метод", "название")
    ).casefold()
    values = [name for name, needles in MODALITY_PATTERNS if any(n in text for n in needles)]
    return sorted(set(values))


def subject_domain(record: dict[str, Any]) -> str:
    text = " ".join(
        str(record.get(field) or "") for field in ("название", "задача", "датасет", "ограничения")
    ).casefold()
    if "drosophila" in text or "дрозофил" in text:
        return "drosophila_larva" if "larv" in text or "личин" in text else "drosophila_adult"
    if any(term in text for term in ("patient", "пациент", "chronic pain", "хроническ", "scs")):
        return "human_clinical"
    if any(
        term in text
        for term in ("participant", "healthy", "испытуем", "bioVid".casefold(), "painmonit")
    ):
        return "human_healthy"
    if any(term in text for term in ("simulation", "synthetic", "симуляц", "синтетич")):
        return "simulation"
    return "unknown"


def assessment_from_legacy(value: Any) -> str:
    if not isinstance(value, str):
        return "not_reported"
    normalized = re.sub(r"\s+", " ", value.strip().casefold())
    if normalized in {"да", "yes"} or normalized.startswith(("да,", "yes,")):
        return "yes"
    if normalized in {"нет", "no"} or normalized.startswith(("нет,", "no,")):
        return "no"
    return "not_reported"


def migrate_record(record: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(record)
    evidence = result.setdefault("evidence", {})
    evidence.setdefault("subject_domain", subject_domain(result))
    evidence.setdefault("modalities", normalized_modalities(result))
    validation = result.setdefault("validation", {})
    validation.setdefault("split_unit", "not_reported")
    validation.setdefault("cross_subject", assessment_from_legacy(result.get("кросс_субъект")))
    validation.setdefault("external_validation", "not_reported")
    validation.setdefault("calibration", "not_reported")
    validation.setdefault("uncertainty", "not_reported")
    validation.setdefault("exclusion_reason", None)
    result.setdefault("relations", [])
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-way migration to source schema 1.2; writes require --apply."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate the plan without writing")
    mode.add_argument("--apply", action="store_true", help="write the migration output")
    return parser.parse_args()


def main(*, apply: bool) -> None:
    records = load_json(DATA / "records.json")
    migrated = [migrate_record(record) for record in records.get("sources", [])]
    records["sources"] = migrated
    meta = records.setdefault("meta", {})
    meta["schema_version"] = "1.2.0"
    meta["version"] = "schema_1_2_relevance_5_curation"
    meta["records_count"] = len(migrated)
    meta["verified_primary_count"] = sum(
        item["validation"]["status"] == "verified_primary" for item in migrated
    )
    meta["unverified_count"] = sum(
        item["validation"]["status"] == "unverified" for item in migrated
    )
    meta["updated_at"] = date.today().isoformat()

    clusters = load_json(DATA / "clusters.json")
    clusters.setdefault("meta", {})["schema_version"] = "1.2.0"
    clusters["meta"]["updated_at"] = date.today().isoformat()
    aliases = load_json(DATA / "aliases.json")
    aliases.setdefault("meta", {})["schema_version"] = "1.2.0"
    aliases["meta"]["updated_at"] = date.today().isoformat()

    evidence_matrix = {
        "meta": {
            "version": "1.0.0",
            "generated_at": date.today().isoformat(),
            "scope": "relevance-5 evidence traceability",
            "gate": "G0_REVISE",
        },
        "columns": [
            "claim",
            "target_variable",
            "population_or_data",
            "source_ids",
            "verified_evidence",
            "limitations",
            "permitted_conclusion",
        ],
        "rows": [],
        "author_review_required": True,
        "supervisor_decision_required": True,
    }

    if not apply:
        print(
            {
                "ok": True,
                "writes": False,
                "records": len(migrated),
                "warning": (
                    "legacy migration would reset evidence-matrix rows; "
                    "do not apply to a curated corpus"
                ),
            }
        )
        return
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "clusters.json", clusters)
    atomic_write_json(DATA / "aliases.json", aliases)
    atomic_write_json(DATA / "evidence-matrix.json", evidence_matrix)


if __name__ == "__main__":
    arguments = parse_args()
    main(apply=arguments.apply)
