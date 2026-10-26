"""Schema-2 validation of a single source record."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..completeness import validate_resolutions

LEGACY_FIELDS = (
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
)


def validate_source_record(
    record: dict[str, Any], schema: dict[str, Any], vocab: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    source_id = str(record.get("id", "<missing>"))
    required = set(schema.get("required", []))
    allowed = set(schema.get("properties", {}))
    missing = required - set(record)
    extra = set(record) - allowed
    if missing:
        errors.append(f"{source_id}: missing fields {sorted(missing)}")
    if extra:
        errors.append(f"{source_id}: unexpected fields {sorted(extra)}")
    if not re.fullmatch(r"S\d{3,}", source_id):
        errors.append(f"{source_id}: invalid id")
    if not isinstance(record.get("название"), str) or not record.get("название", "").strip():
        errors.append(f"{source_id}: empty title")
    relevance = record.get("релевантность")
    if not isinstance(relevance, int) or isinstance(relevance, bool) or not 1 <= relevance <= 5:
        errors.append(f"{source_id}: relevance must be integer 1..5")
    year = record.get("год")
    if year is not None and (
        not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 2100
    ):
        errors.append(f"{source_id}: invalid year {year!r}")
    for field in LEGACY_FIELDS:
        if record.get(field) == "Не указано":
            errors.append(f"{source_id}: placeholder remains in {field}")
    if schema.get("title", "").endswith("schema 2.0"):
        errors.extend(validate_resolutions(record))

    validation = record.get("validation")
    evidence = record.get("evidence")
    identifiers = record.get("identifiers")
    provenance = record.get("provenance")
    if not isinstance(validation, dict):
        errors.append(f"{source_id}: validation must be an object")
        validation = {}
    if not isinstance(evidence, dict):
        errors.append(f"{source_id}: evidence must be an object")
        evidence = {}
    if not isinstance(identifiers, dict):
        errors.append(f"{source_id}: identifiers must be an object")
        identifiers = {}
    if not isinstance(provenance, dict):
        errors.append(f"{source_id}: provenance must be an object")
        provenance = {}

    checks = (
        (validation.get("status"), "validation_status", "validation status"),
        (validation.get("screening_status"), "screening_status", "screening status"),
        (validation.get("full_text_status"), "full_text_status", "full-text status"),
        (evidence.get("target_construct"), "target_construct", "target construct"),
        (evidence.get("access_status"), "access_status", "access status"),
        (evidence.get("evidence_role"), "evidence_role", "evidence role"),
        (evidence.get("subject_domain"), "subject_domain", "subject domain"),
        (validation.get("split_unit"), "split_unit", "split unit"),
        (validation.get("cross_subject"), "assessment_result", "cross-subject result"),
        (
            validation.get("external_validation"),
            "assessment_result",
            "external-validation result",
        ),
        (validation.get("calibration"), "assessment_result", "calibration result"),
        (validation.get("uncertainty"), "assessment_result", "uncertainty result"),
    )
    for value, vocabulary_name, label in checks:
        if value not in vocab.get(vocabulary_name, []):
            errors.append(f"{source_id}: invalid {label}: {value!r}")

    flags = record.get("risk_flags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        errors.append(f"{source_id}: risk_flags must be an array of strings")
    else:
        unknown_flags = set(flags) - set(vocab.get("risk_flags", []))
        if unknown_flags:
            errors.append(f"{source_id}: unknown risk flags {sorted(unknown_flags)}")
        if len(flags) != len(set(flags)):
            errors.append(f"{source_id}: duplicate risk flags")

    modalities = evidence.get("modalities")
    if not isinstance(modalities, list) or any(
        not isinstance(modality, str) for modality in modalities
    ):
        errors.append(f"{source_id}: evidence.modalities must be an array of strings")
    else:
        unknown_modalities = set(modalities) - set(vocab.get("modality", []))
        if unknown_modalities:
            errors.append(f"{source_id}: unknown modalities {sorted(unknown_modalities)}")
        if len(modalities) != len(set(modalities)):
            errors.append(f"{source_id}: duplicate modalities")

    exclusion_reason = validation.get("exclusion_reason")
    if exclusion_reason is not None and exclusion_reason not in vocab.get("exclusion_reason", []):
        errors.append(f"{source_id}: invalid exclusion reason: {exclusion_reason!r}")
    if validation.get("status") == "rejected" and exclusion_reason is None:
        errors.append(f"{source_id}: rejected record requires exclusion_reason")

    relations = record.get("relations")
    if not isinstance(relations, list):
        errors.append(f"{source_id}: relations must be an array")
    else:
        seen_relations: set[tuple[Any, Any, Any]] = set()
        for relation in relations:
            if not isinstance(relation, dict):
                errors.append(f"{source_id}: relation must be an object")
                continue
            relation_type = relation.get("type")
            if relation_type not in vocab.get("relation_type", []):
                errors.append(f"{source_id}: invalid relation type {relation_type!r}")
            target_id = relation.get("target_id")
            external_id = relation.get("external_id")
            if bool(target_id) == bool(external_id):
                errors.append(
                    f"{source_id}: relation requires exactly one of target_id/external_id"
                )
            key = (relation_type, target_id, external_id)
            if key in seen_relations:
                errors.append(f"{source_id}: duplicate relation {key!r}")
            seen_relations.add(key)

    source_type = record.get("тип_источника")
    if source_type not in vocab.get("source_type", []):
        errors.append(f"{source_id}: invalid source type: {source_type!r}")

    exact_url = identifiers.get("exact_url")
    if exact_url:
        parsed = urlsplit(str(exact_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{source_id}: invalid exact_url")
    if not provenance.get("import_source"):
        errors.append(f"{source_id}: missing provenance.import_source")
    return errors
