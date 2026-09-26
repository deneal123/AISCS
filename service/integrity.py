"""Dependency-free integrity gates for canonical research artifacts."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .completeness import RESOLUTION_STATES, completeness_summary, validate_resolutions
from .core import DataError, load_json, sha256
from .novelty import validate_novelty_artifacts

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


def _load_required(root: Path, name: str, errors: list[str]) -> dict[str, Any]:
    try:
        return load_json(root / name)
    except DataError as exc:
        errors.append(str(exc))
        return {}


def _validate_ecap_scs_audit(
    audit: dict[str, Any], canonical_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append("ECAP/SCS audit: unsupported schema version")
    dimensions = ("sample", "electrode_geometry", "stimulation", "split_unit", "metrics")
    allowed_states = {
        "reported",
        "not_reported",
        "not_applicable",
        "unavailable_after_search",
    }
    entries = audit.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + ["ECAP/SCS audit: non-empty entries array required"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("ECAP/SCS audit: entry must be an object")
            continue
        source_id = entry.get("source_id")
        if source_id not in canonical_ids:
            errors.append(f"ECAP/SCS audit: missing source {source_id!r}")
        if source_id in seen:
            errors.append(f"ECAP/SCS audit: duplicate source {source_id}")
        seen.add(source_id)
        extraction = entry.get("extraction")
        if not isinstance(extraction, dict):
            errors.append(f"ECAP/SCS audit: {source_id} lacks extraction")
            continue
        if set(extraction) != set(dimensions):
            errors.append(f"ECAP/SCS audit: {source_id} requires exactly {dimensions}")
        for dimension in dimensions:
            item = extraction.get(dimension)
            if not isinstance(item, dict):
                errors.append(f"ECAP/SCS audit: {source_id}.{dimension} must be an object")
                continue
            state = item.get("state")
            value = item.get("value")
            if state not in allowed_states:
                errors.append(f"ECAP/SCS audit: {source_id}.{dimension} bad state {state!r}")
            if state == "reported" and value in (None, "", []):
                errors.append(f"ECAP/SCS audit: {source_id}.{dimension} reported without value")
            if state != "reported" and value is not None:
                errors.append(
                    f"ECAP/SCS audit: {source_id}.{dimension} terminal state must use null"
                )
            if not item.get("reason") or not item.get("checked_at"):
                errors.append(f"ECAP/SCS audit: {source_id}.{dimension} lacks reason/date")
            locators = item.get("locators")
            if not isinstance(locators, list) or not locators:
                errors.append(f"ECAP/SCS audit: {source_id}.{dimension} lacks locators")
                continue
            for locator in locators:
                if (
                    not isinstance(locator, dict)
                    or not locator.get("url")
                    or not locator.get("locator")
                ):
                    errors.append(f"ECAP/SCS audit: {source_id}.{dimension} has invalid locator")
    if audit.get("meta", {}).get("records_count") != len(entries):
        errors.append("ECAP/SCS audit: records_count mismatch")
    return errors


def _validate_drosophila_connectome_audit(
    audit: dict[str, Any], canonical_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    label = "Drosophila connectome audit"
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append(f"{label}: unsupported schema version")
    dimensions = (
        "connectome_version",
        "organism_sex_stage",
        "dynamic_model",
        "experimental_comparator",
        "scope_boundary",
    )
    allowed_states = {
        "reported",
        "not_reported",
        "not_applicable",
        "unavailable_after_search",
    }
    entries = audit.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + [f"{label}: non-empty entries array required"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        source_id = entry.get("source_id")
        if source_id not in canonical_ids:
            errors.append(f"{label}: missing source {source_id!r}")
        if source_id in seen:
            errors.append(f"{label}: duplicate source {source_id}")
        seen.add(source_id)
        extraction = entry.get("extraction")
        if not isinstance(extraction, dict):
            errors.append(f"{label}: {source_id} lacks extraction")
            continue
        if set(extraction) != set(dimensions):
            errors.append(f"{label}: {source_id} requires exactly {dimensions}")
        for dimension in dimensions:
            item = extraction.get(dimension)
            if not isinstance(item, dict):
                errors.append(f"{label}: {source_id}.{dimension} must be an object")
                continue
            state = item.get("state")
            value = item.get("value")
            if state not in allowed_states:
                errors.append(f"{label}: {source_id}.{dimension} bad state {state!r}")
            if state == "reported" and value in (None, "", []):
                errors.append(f"{label}: {source_id}.{dimension} lacks value")
            if state != "reported" and value is not None:
                errors.append(f"{label}: {source_id}.{dimension} terminal value must be null")
            if not item.get("reason") or not item.get("checked_at"):
                errors.append(f"{label}: {source_id}.{dimension} lacks reason/date")
            locators = item.get("locators")
            if not isinstance(locators, list) or not locators:
                errors.append(f"{label}: {source_id}.{dimension} lacks locators")
                continue
            if any(
                not isinstance(locator, dict)
                or not locator.get("url")
                or not locator.get("locator")
                for locator in locators
            ):
                errors.append(f"{label}: {source_id}.{dimension} has invalid locator")
    if audit.get("meta", {}).get("records_count") != len(entries):
        errors.append(f"{label}: records_count mismatch")
    return errors


def _validate_human_ecap_access_audit(
    audit: dict[str, Any], canonical_ids: set[str]
) -> list[str]:
    label = "human ECAP/SCS access audit"
    errors: list[str] = []
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append(f"{label}: unsupported schema version")
    candidates = audit.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return errors + [f"{label}: non-empty candidates required"]
    dimensions = {
        "access_procedure",
        "ethics_secondary_use",
        "consent_dua",
        "patient_linkage",
        "outcomes",
        "ecap_signal",
    }
    allowed = {
        "confirmed_by_owner",
        "confirmed_by_institution",
        "confirmed_in_study",
        "partial",
        "planned",
        "unconfirmed",
        "conflicting",
    }
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            errors.append(f"{label}: candidate must be an object")
            continue
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, str) or candidate_id in seen:
            errors.append(f"{label}: candidate IDs must be present and unique")
        else:
            seen.add(candidate_id)
        if not candidate.get("owner") or not candidate.get("trial_id"):
            errors.append(f"{label}: {candidate_id} lacks owner/trial")
        source_refs = candidate.get("source_refs")
        if not isinstance(source_refs, list) or any(
            ref not in canonical_ids for ref in source_refs
        ):
            errors.append(f"{label}: {candidate_id} has an unknown source reference")
        checks = candidate.get("checks")
        if not isinstance(checks, dict) or set(checks) != dimensions:
            errors.append(f"{label}: {candidate_id} requires exactly {sorted(dimensions)}")
            continue
        for dimension, item in checks.items():
            if not isinstance(item, dict) or item.get("state") not in allowed:
                errors.append(f"{label}: {candidate_id}.{dimension} invalid state")
                continue
            if (
                not item.get("finding")
                or not isinstance(item.get("locators"), list)
                or not item["locators"]
            ):
                errors.append(f"{label}: {candidate_id}.{dimension} lacks finding/locators")
                continue
            for locator in item["locators"]:
                if (
                    not isinstance(locator, dict)
                    or not locator.get("url")
                    or not locator.get("locator")
                ):
                    errors.append(f"{label}: {candidate_id}.{dimension} invalid locator")
        if candidate.get("owner_confirmation_received") and not candidate.get(
            "owner_confirmation_evidence"
        ):
            errors.append(f"{label}: {candidate_id} lacks owner confirmation evidence")
        if candidate.get("decision") == "usable":
            if not candidate.get("owner_confirmation_received"):
                errors.append(
                    f"{label}: {candidate_id} cannot be usable without owner confirmation"
                )
            elif (
                not isinstance(checks.get("ethics_secondary_use"), dict)
                or checks["ethics_secondary_use"].get("state") != "confirmed_by_institution"
            ):
                errors.append(
                    f"{label}: {candidate_id} cannot be usable without institutional ethics "
                    "determination"
                )
            elif any(
                not isinstance(checks.get(dimension), dict)
                or checks[dimension].get("state") != "confirmed_by_owner"
                for dimension in dimensions - {"ethics_secondary_use"}
            ):
                errors.append(
                    f"{label}: {candidate_id} cannot be usable with unresolved owner-controlled "
                    "checks"
                )
    if audit.get("meta", {}).get("decision") == "owner_confirmed_usable_dataset" and not any(
        item.get("decision") == "usable" for item in candidates if isinstance(item, dict)
    ):
        errors.append(f"{label}: positive decision lacks a usable candidate")
    return errors


def _validate_resolution_audit(
    audit: dict[str, Any],
    canonical_ids: set[str],
    *,
    label: str,
    dimensions: set[str],
) -> list[str]:
    errors: list[str] = []
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append(f"{label}: unsupported schema version")
    entries = audit.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + [f"{label}: non-empty entries array required"]
    states = {"reported", "not_reported", "not_applicable", "unavailable_after_search"}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry must be an object")
            continue
        source_id = entry.get("source_id")
        if source_id not in canonical_ids or source_id in seen:
            errors.append(f"{label}: missing or duplicate source {source_id!r}")
        seen.add(source_id)
        extraction = entry.get("extraction")
        if not isinstance(extraction, dict) or set(extraction) != dimensions:
            errors.append(f"{label}: {source_id} requires {sorted(dimensions)}")
            continue
        for dimension, item in extraction.items():
            if not isinstance(item, dict):
                errors.append(f"{label}: {source_id}.{dimension} must be an object")
                continue
            state = item.get("state")
            value = item.get("value")
            if (
                state not in states
                or (state == "reported" and value in (None, "", []))
                or (state != "reported" and value is not None)
            ):
                errors.append(f"{label}: {source_id}.{dimension} has invalid state/value")
            if not item.get("reason") or not item.get("checked_at"):
                errors.append(f"{label}: {source_id}.{dimension} lacks reason/date")
            locators = item.get("locators")
            if not isinstance(locators, list) or not locators or any(
                not isinstance(locator, dict)
                or not locator.get("url")
                or not locator.get("locator")
                for locator in locators
            ):
                errors.append(f"{label}: {source_id}.{dimension} lacks primary locator")
    if audit.get("meta", {}).get("records_count") != len(entries):
        errors.append(f"{label}: records_count mismatch")
    return errors


def _validate_ns06_prior_art_audit(
    audit: dict[str, Any], canonical_ids: set[str], variant_ids: set[str]
) -> list[str]:
    label = "NS-06 prior-art audit"
    errors: list[str] = []
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append(f"{label}: unsupported schema version")
    if audit.get("meta", {}).get("status") != "open":
        errors.append(f"{label}: status must remain open while remaining checks exist")
    baseline = audit.get("s149_baseline", {})
    if baseline.get("source_id") != "S149" or not baseline.get("mechanism"):
        errors.append(f"{label}: missing S149 mechanism baseline")
    baseline_locator = baseline.get("locator")
    if (
        not isinstance(baseline_locator, dict)
        or not baseline_locator.get("url")
        or not baseline_locator.get("section")
    ):
        errors.append(f"{label}: S149 baseline lacks primary locator")
    entries = audit.get("analogue_decisions")
    if not isinstance(entries, list) or not entries:
        return errors + [f"{label}: non-empty analogue_decisions required"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"{label}: analogue entry must be an object")
            continue
        source_id = entry.get("source_id")
        if source_id not in canonical_ids or source_id in seen:
            errors.append(f"{label}: unknown or duplicate source {source_id!r}")
        seen.add(source_id)
        if not entry.get("mechanism") or not entry.get("relation_to_s149"):
            errors.append(f"{label}: {source_id} lacks mechanism decision")
        locator = entry.get("locator")
        if not isinstance(locator, dict) or not locator.get("url") or not locator.get("section"):
            errors.append(f"{label}: {source_id} lacks primary locator")
    if not {"S758", "S759"}.issubset(seen):
        errors.append(f"{label}: new synthetic analogues are missing")
    decisions = audit.get("variant_decisions", [])
    if not isinstance(decisions, list) or not decisions:
        errors.append(f"{label}: variant decisions required")
    else:
        for item in decisions:
            if not isinstance(item, dict) or item.get("variant_id") not in variant_ids:
                errors.append(f"{label}: unknown variant decision")
            elif not item.get("decision") or not item.get("reason"):
                errors.append(f"{label}: incomplete variant decision")
    forward = audit.get("citation_search", {}).get("s149_forward", {})
    if forward.get("state") == "no_indexed_citation_found" and not forward.get("limit"):
        errors.append(f"{label}: zero-indexed-citation claim lacks coverage limit")
    if not audit.get("remaining"):
        errors.append(f"{label}: open audit lacks remaining checks")
    return errors


def _validate_scientific_artifacts(
    contract: dict[str, Any],
    matrix: dict[str, Any],
    canonical_ids: set[str],
    resource_ids: set[str],
    vocab: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if contract.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append("scientific contract: unsupported schema version")
    if contract.get("meta", {}).get("gate") != "G0_REVISE":
        errors.append("scientific contract: G0 must remain G0_REVISE")

    expected_entities = {f"ENT-{index:02d}" for index in range(1, 7)}
    entities = contract.get("entities", [])
    entity_ids = [item.get("id") for item in entities if isinstance(item, dict)]
    if set(entity_ids) != expected_entities or len(entity_ids) != len(expected_entities):
        errors.append("scientific contract: exactly six unique entities ENT-01..ENT-06 required")
    experiment_ids = [
        item.get("id") for item in contract.get("experiments", []) if isinstance(item, dict)
    ]
    if experiment_ids != ["EXP-01", "EXP-02", "EXP-03", "EXP-04"]:
        errors.append("scientific contract: four ordered experiments EXP-01..EXP-04 required")
    for experiment in contract.get("experiments", []):
        if experiment.get("primary_entity_id") not in expected_entities:
            errors.append(f"scientific contract: bad entity in {experiment.get('id')}")
        for field in (
            "input",
            "output",
            "training_data",
            "independent_test",
            "success_criterion",
            "falsification_criterion",
        ):
            if not experiment.get(field):
                errors.append(f"scientific contract: {experiment.get('id')} lacks {field}")

    transfer_ids = [
        item.get("id") for item in contract.get("transfer_chain", []) if isinstance(item, dict)
    ]
    if transfer_ids != ["TR-01", "TR-02", "TR-03", "TR-04"]:
        errors.append("scientific contract: four ordered transfers TR-01..TR-04 required")
    expected_stops = {"STOP-H1", "STOP-H2-A", "STOP-H2-B", "STOP-H3-A", "STOP-H3-B"}
    stops = contract.get("stop_criteria", [])
    stop_ids = [item.get("id") for item in stops if isinstance(item, dict)]
    if set(stop_ids) != expected_stops or len(stop_ids) != len(expected_stops):
        errors.append("scientific contract: incomplete or duplicate STOP registry")
    for stop in stops:
        for field in (
            "trigger",
            "measurement",
            "decision",
            "reserve_result",
            "forbidden_conclusion",
        ):
            if not stop.get(field):
                errors.append(f"scientific contract: {stop.get('id')} lacks {field}")

    observation = contract.get("ecap_like_observation_model", {})
    if observation.get("required_term_before_validation") != "ECAP-like":
        errors.append("scientific contract: unvalidated observation must remain ECAP-like")
    tolerance = observation.get("tolerance_protocol", {})
    numeric_bounds = tolerance.get("numeric_bounds", "missing")
    if tolerance.get("status") == "specified_pending_human_signal_access":
        if numeric_bounds is not None:
            errors.append("scientific contract: pending ECAP-like bounds must be null")
    elif not isinstance(numeric_bounds, dict) or not numeric_bounds:
        errors.append("scientific contract: validated ECAP-like bounds must be non-empty")

    if matrix.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append("human dataset matrix: unsupported schema version")
    datasets = matrix.get("datasets", [])
    dataset_ids = [item.get("id") for item in datasets if isinstance(item, dict)]
    if len(dataset_ids) != len(set(dataset_ids)) or not dataset_ids:
        errors.append("human dataset matrix: dataset IDs must be non-empty and unique")
    allowed_targets = set(vocab.get("target_construct", []))
    allowed_modalities = set(vocab.get("modality", []))
    allowed_access = set(vocab.get("access_status", []))
    for dataset in datasets:
        dataset_id = dataset.get("id")
        if dataset.get("target_construct") not in allowed_targets:
            errors.append(f"human dataset matrix: invalid target for {dataset_id}")
        if dataset.get("access_status") not in allowed_access:
            errors.append(f"human dataset matrix: invalid access status for {dataset_id}")
        unknown_modalities = set(dataset.get("modalities", [])) - allowed_modalities
        if unknown_modalities:
            errors.append(
                f"human dataset matrix: unknown modalities for {dataset_id}: "
                f"{sorted(unknown_modalities)}"
            )
        parsed = urlsplit(str(dataset.get("primary_url", "")))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"human dataset matrix: invalid primary URL for {dataset_id}")
        if dataset.get("split_unit") != "participant":
            errors.append(f"human dataset matrix: participant split required for {dataset_id}")

    by_dataset = {item.get("id"): item for item in datasets if isinstance(item, dict)}
    compatibility_ids: list[str] = []
    for rule in matrix.get("compatibility_rules", []):
        compatibility_ids.append(rule.get("id"))
        for dataset_id in rule.get("dataset_ids", []):
            dataset = by_dataset.get(dataset_id)
            if dataset is None:
                errors.append(
                    f"human dataset matrix: missing dataset {dataset_id} "
                    "in compatibility rule"
                )
            elif dataset.get("target_construct") != rule.get("target_construct"):
                errors.append(f"human dataset matrix: mixed targets in {rule.get('id')}")
    if len(compatibility_ids) != len(set(compatibility_ids)):
        errors.append("human dataset matrix: duplicate compatibility rule IDs")

    def check_refs(owner: str, refs: Any) -> None:
        if not isinstance(refs, list):
            errors.append(f"{owner}: source_refs must be an array")
            return
        for ref in refs:
            if isinstance(ref, str) and ref.startswith("ST"):
                if ref not in resource_ids:
                    errors.append(f"{owner}: missing resource reference {ref}")
            elif isinstance(ref, str) and ref.startswith("S"):
                if ref not in canonical_ids:
                    errors.append(f"{owner}: missing source reference {ref}")
            else:
                errors.append(f"{owner}: invalid source reference {ref!r}")

    for collection_name in ("entities", "experiments", "transfer_chain", "stop_criteria"):
        for item in contract.get(collection_name, []):
            check_refs(f"scientific contract {item.get('id')}", item.get("source_refs", []))
    simulation_domain = contract.get("simulation_domain", {})
    if simulation_domain.get("id") != "SIM-DOM-01":
        errors.append("scientific contract: simulation domain SIM-DOM-01 required")
    check_refs(
        "scientific contract SIM-DOM-01", simulation_domain.get("source_refs", [])
    )
    check_refs("scientific contract ECAP-OBS-01", observation.get("human_comparators", []))
    for dataset in datasets:
        check_refs(f"human dataset matrix {dataset.get('id')}", dataset.get("source_refs", []))
    return errors


def validate_repository(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    records = _load_required(root, "records.json", errors)
    clusters = _load_required(root, "clusters.json", errors)
    resources = _load_required(root, "ST.json", errors)
    aliases = _load_required(root, "aliases.json", errors)
    schema = _load_required(root, "source-record.schema.json", errors)
    vocab = _load_required(root, "vocabularies.json", errors)
    contract_path = root / "scientific-contract.json"
    matrix_path = root / "human-dataset-matrix.json"
    novelty_path = root / "novelty-landscape.json"
    concept_path = root / "dissertation-concept.json"
    search_path = root / "search-protocol.json"
    runtime_path = root / "runtime-audit.json"
    ecap_scs_audit_path = root / "ecap-scs-audit.json"
    connectome_audit_path = root / "drosophila-connectome-audit.json"
    nociception_audit_path = root / "drosophila-nociception-audit.json"
    synthetic_audit_path = root / "synthetic-domain-audit.json"
    ns06_audit_path = root / "ns06-prior-art-audit.json"
    scs_outcome_audit_path = root / "scs-outcome-audit.json"
    ns11_audit_path = root / "ns11-prediction-audit.json"
    human_ecap_access_path = root / "human-ecap-scs-access-audit.json"
    has_scientific_artifacts = contract_path.is_file() or matrix_path.is_file()
    if (root / "staging").is_dir() or has_scientific_artifacts:
        contract = _load_required(root, "scientific-contract.json", errors)
        human_datasets = _load_required(root, "human-dataset-matrix.json", errors)
    else:
        contract = {}
        human_datasets = {}
    has_novelty_artifacts = (
        novelty_path.is_file() or concept_path.is_file() or search_path.is_file()
    )
    if has_novelty_artifacts:
        novelty = _load_required(root, "novelty-landscape.json", errors)
        concept = _load_required(root, "dissertation-concept.json", errors)
        search_protocol = _load_required(root, "search-protocol.json", errors)
        completeness = _load_required(root, "completeness-report.json", errors)
        runtime_audit = _load_required(root, runtime_path.name, errors)
        ecap_scs_audit = (
            _load_required(root, ecap_scs_audit_path.name, errors)
            if ecap_scs_audit_path.is_file()
            else {}
        )
        connectome_audit = (
            _load_required(root, connectome_audit_path.name, errors)
            if connectome_audit_path.is_file()
            else {}
        )
        nociception_audit = (
            _load_required(root, nociception_audit_path.name, errors)
            if nociception_audit_path.is_file()
            else {}
        )
        synthetic_audit = (
            _load_required(root, synthetic_audit_path.name, errors)
            if synthetic_audit_path.is_file()
            else {}
        )
        ns06_audit = (
            _load_required(root, ns06_audit_path.name, errors)
            if ns06_audit_path.is_file()
            else {}
        )
        scs_outcome_audit = (
            _load_required(root, scs_outcome_audit_path.name, errors)
            if scs_outcome_audit_path.is_file()
            else {}
        )
        ns11_audit = (
            _load_required(root, ns11_audit_path.name, errors)
            if ns11_audit_path.is_file()
            else {}
        )
        human_ecap_access = (
            _load_required(root, human_ecap_access_path.name, errors)
            if human_ecap_access_path.is_file()
            else {}
        )
    else:
        novelty = {}
        concept = {}
        search_protocol = {}
        completeness = {}
        runtime_audit = {}
        ecap_scs_audit = {}
        connectome_audit = {}
        nociception_audit = {}
        synthetic_audit = {}
        ns06_audit = {}
        scs_outcome_audit = {}
        ns11_audit = {}
        human_ecap_access = {}
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "counts": {}}

    sources = records.get("sources", [])
    if not isinstance(sources, list):
        errors.append("records.sources must be an array")
        sources = []
    ids = [record.get("id") for record in sources if isinstance(record, dict)]
    if len(ids) != len(sources):
        errors.append("records.sources contains a non-object item")
    if len(ids) != len(set(ids)):
        errors.append("records: duplicate ids")
    if records.get("meta", {}).get("records_count") != len(sources):
        errors.append("records: meta.records_count mismatch")
    runtime_candidates = runtime_audit.get("candidates", [])
    if not isinstance(runtime_candidates, list):
        errors.append("runtime audit: candidates must be an array")
        runtime_candidates = []
    runtime_ids = [
        item.get("resource_id") for item in runtime_candidates if isinstance(item, dict)
    ]
    if len(runtime_ids) != len(runtime_candidates) or len(runtime_ids) != len(
        set(runtime_ids)
    ):
        errors.append("runtime audit: candidate resource IDs must be present and unique")
    for record in sources:
        if isinstance(record, dict):
            errors.extend(validate_source_record(record, schema, vocab))

    exact_keys: list[str] = []
    for record in sources:
        if not isinstance(record, dict):
            continue
        payload = {key: record.get(key) for key in LEGACY_FIELDS}
        payload["название"] = str(payload.get("название") or "").casefold()
        exact_keys.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if len(exact_keys) != len(set(exact_keys)):
        errors.append("records: exact duplicates remain")

    identifier_fields = ("doi", "pmid", "arxiv_id", "patent_id", "dataset_id")
    seen_identifiers: dict[tuple[str, str], str] = {}
    for record in sources:
        if not isinstance(record, dict):
            continue
        source_id = str(record.get("id"))
        identifiers = record.get("identifiers", {})
        for field in identifier_fields:
            raw_value = identifiers.get(field) if isinstance(identifiers, dict) else None
            if not isinstance(raw_value, str) or not raw_value.strip():
                continue
            value = raw_value.strip().casefold()
            if field == "doi":
                value = value.removeprefix("https://doi.org/").removeprefix("doi:")
            key = (field, value)
            previous = seen_identifiers.get(key)
            if previous:
                errors.append(
                    f"records: duplicate {field} {raw_value!r} in {previous} and {source_id}"
                )
            else:
                seen_identifiers[key] = source_id

    canonical_ids = set(ids)
    if ecap_scs_audit:
        errors.extend(_validate_ecap_scs_audit(ecap_scs_audit, canonical_ids))
    if connectome_audit:
        errors.extend(_validate_drosophila_connectome_audit(connectome_audit, canonical_ids))
    if nociception_audit:
        errors.extend(
            _validate_resolution_audit(
                nociception_audit,
                canonical_ids,
                label="Drosophila nociception audit",
                dimensions={"stimulus", "neural_response", "behavior", "pain_boundary"},
            )
        )
        ns03 = next(
            (
                item
                for item in search_protocol.get("search_streams", [])
                if item.get("id") == "NS-03"
            ),
            {},
        )
        candidate_ids = nociception_audit.get("meta", {}).get("candidate_source_ids", [])
        remaining_ids = nociception_audit.get("meta", {}).get("remaining_source_ids", [])
        reviewed_ids = [entry.get("source_id") for entry in nociception_audit.get("entries", [])]
        if (
            not isinstance(candidate_ids, list)
            or not isinstance(remaining_ids, list)
            or len(candidate_ids) != len(set(candidate_ids))
            or len(remaining_ids) != len(set(remaining_ids))
            or set(candidate_ids) != set(ns03.get("source_ids", []))
            or set(reviewed_ids) & set(remaining_ids)
            or set(reviewed_ids) | set(remaining_ids) != set(candidate_ids)
        ):
            errors.append("Drosophila nociception audit: NS-03 candidate coverage mismatch")
    if human_ecap_access:
        errors.extend(_validate_human_ecap_access_audit(human_ecap_access, canonical_ids))
    if synthetic_audit:
        errors.extend(
            _validate_resolution_audit(
                synthetic_audit,
                canonical_ids,
                label="synthetic/domain audit",
                dimensions={
                    "real_data_provenance",
                    "leakage_control",
                    "split_unit",
                    "external_test",
                },
            )
        )
    if ns06_audit:
        variant_ids = {
            variant.get("id")
            for variant in novelty.get("variants", [])
            if isinstance(variant, dict)
        }
        errors.extend(_validate_ns06_prior_art_audit(ns06_audit, canonical_ids, variant_ids))
    if scs_outcome_audit:
        errors.extend(
            _validate_resolution_audit(
                scs_outcome_audit,
                canonical_ids,
                label="SCS outcome audit",
                dimensions={"input_role", "target_role", "study_design", "prognostic_validation"},
            )
        )
    if ns11_audit:
        errors.extend(
            _validate_resolution_audit(
                ns11_audit,
                canonical_ids,
                label="NS-11 prediction audit",
                dimensions={"target", "follow_up", "patient_linkage"},
            )
        )
    for record in sources:
        if not isinstance(record, dict):
            continue
        for relation in record.get("relations", []):
            target_id = relation.get("target_id") if isinstance(relation, dict) else None
            if target_id and target_id not in canonical_ids:
                errors.append(
                    f"relations: {record.get('id')} points to missing canonical {target_id}"
                )
    alias_map = aliases.get("aliases", {})
    if not isinstance(alias_map, dict):
        errors.append("aliases.aliases must be an object")
        alias_map = {}
    if aliases.get("meta", {}).get("aliases_count") != len(alias_map):
        errors.append("aliases: meta.aliases_count mismatch")
    for alias, entry in alias_map.items():
        if alias in canonical_ids:
            errors.append(f"aliases: alias {alias} remains canonical")
        if not isinstance(entry, dict) or entry.get("canonical_id") not in canonical_ids:
            errors.append(f"aliases: {alias} points to a missing canonical record")
    for alias in alias_map:
        seen: set[str] = set()
        current = alias
        while current in alias_map:
            if current in seen:
                errors.append(f"aliases: cycle detected from {alias}")
                break
            seen.add(current)
            entry = alias_map.get(current)
            if not isinstance(entry, dict):
                break
            current = str(entry.get("canonical_id"))

    canonical_by_id = {
        source["id"]: source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    active_clusters = clusters.get("clusters", [])
    if clusters.get("meta", {}).get("clusters_count") != len(active_clusters):
        errors.append("clusters: meta.clusters_count mismatch")
    refs: list[str] = []
    for cluster in active_clusters:
        members = cluster.get("состав_кластера", [])
        refs.extend(members)
        cluster_id = cluster.get("id")
        if not members:
            errors.append(f"clusters: active cluster {cluster_id} is empty")
        if cluster.get("записей") != len(members):
            errors.append(f"clusters: count mismatch in {cluster_id}")
        if len(members) != len(set(members)):
            errors.append(f"clusters: duplicate member in {cluster_id}")
        missing = set(members) - canonical_ids
        if missing:
            errors.append(f"clusters: missing refs in {cluster_id}: {sorted(missing)}")
        representative_record = cluster.get("представитель") or {}
        representative = representative_record.get("id")
        if representative not in members:
            errors.append(f"clusters: invalid representative in {cluster_id}")
        if (
            str(records.get("meta", {}).get("schema_version", "")).startswith("2.")
            and representative in canonical_by_id
            and representative_record != canonical_by_id[representative]
        ):
            errors.append(f"clusters: stale representative in {cluster_id}: {representative}")
    cluster_meta = clusters.get("meta", {})
    if cluster_meta.get("cluster_references_count") != len(refs):
        errors.append("clusters: reference count mismatch")
    if cluster_meta.get("unique_clustered_records_count") != len(set(refs)):
        errors.append("clusters: unique reference count mismatch")
    if set(clusters.get("unclustered_record_ids", [])) != canonical_ids - set(refs):
        errors.append("clusters: unclustered_record_ids mismatch")
    unclustered_decisions = clusters.get("unclustered_decisions", {})
    if not isinstance(unclustered_decisions, dict):
        errors.append("clusters: unclustered_decisions must be an object")
    else:
        misplaced_decisions = set(unclustered_decisions) - (canonical_ids - set(refs))
        if misplaced_decisions:
            errors.append(
                "clusters: unclustered_decisions reference clustered or unknown records: "
                f"{sorted(misplaced_decisions)}"
            )
    expected_multi = {source_id: count for source_id, count in Counter(refs).items() if count > 1}
    if clusters.get("multiple_membership", {}) != expected_multi:
        errors.append("clusters: multiple_membership mismatch")

    resource_items = [
        resource
        for category in resources.get("categories", [])
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
    ]
    if resources.get("meta", {}).get("всего_ресурсов") != len(resource_items):
        errors.append("ST: resource count mismatch")
    resource_schema = resources.get("meta", {}).get("resource_schema_version")
    resource_ids: list[str] = []
    resource_statuses = Counter()
    for resource in resource_items:
        if "статус_валидации" not in resource:
            errors.append(f"ST: resource lacks validation status: {resource.get('название')}")
            continue
        status = resource["статус_валидации"]
        resource_statuses[status] += 1
        if resource_schema in {"1.2.0", "2.0.0"}:
            resource_id = resource.get("resource_id")
            if not isinstance(resource_id, str) or not re.fullmatch(r"ST\d{3,}", resource_id):
                errors.append(f"ST: invalid resource_id {resource_id!r}")
            else:
                resource_ids.append(resource_id)
            if status not in vocab.get("resource_validation_status", []):
                errors.append(f"ST: invalid resource status {status!r} for {resource_id}")
            claims = resource.get("проверенные_утверждения")
            limitations = resource.get("ограничения_валидации")
            if not isinstance(claims, list) or not isinstance(limitations, list):
                errors.append(f"ST: normalized claims/limitations missing for {resource_id}")
            if status in {"verified_primary", "verified_metadata"}:
                url = resource.get("ссылка")
                parsed = urlsplit(str(url or ""))
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    errors.append(f"ST: verified resource {resource_id} lacks exact URL")
                if not resource.get("проверено"):
                    errors.append(f"ST: verified resource {resource_id} lacks checked date")
            if resource_schema == "2.0.0":
                technical = resource.get("technical_resolution")
                expected = {"version_or_commit", "license", "data_access", "reproducibility"}
                if not isinstance(technical, dict) or set(technical) != expected:
                    errors.append(f"ST: incomplete technical resolution for {resource_id}")
                else:
                    for field, resolution in technical.items():
                        state = resolution.get("state") if isinstance(resolution, dict) else None
                        if state not in RESOLUTION_STATES:
                            errors.append(
                                f"ST: invalid {field} resolution state for {resource_id}"
                            )
                        if not resolution.get("reason") or not resolution.get("checked_at"):
                            errors.append(f"ST: incomplete {field} resolution for {resource_id}")
                        if not resolution.get("locators"):
                            errors.append(f"ST: missing {field} locator for {resource_id}")
                        if state == "reported" and resolution.get("value") is None:
                            errors.append(f"ST: reported {field} lacks value for {resource_id}")
                        if state != "reported" and resolution.get("value") is not None:
                            errors.append(f"ST: terminal {field} has value for {resource_id}")
    if resource_schema in {"1.2.0", "2.0.0"}:
        if len(resource_ids) != len(set(resource_ids)):
            errors.append("ST: duplicate resource IDs")
        missing_runtime_resources = set(runtime_ids) - set(resource_ids)
        if missing_runtime_resources:
            errors.append(
                "runtime audit: missing ST resource IDs "
                f"{sorted(missing_runtime_resources)}"
            )
        if resources.get("meta", {}).get("статусы_ресурсов") != dict(
            sorted(resource_statuses.items())
        ):
            errors.append("ST: resource status counters mismatch")
        compatibility_counts = {
            "проверено_по_первичному_источнику": resource_statuses["verified_primary"],
            "требуют_точной_ссылки": resource_statuses["needs_exact_url"],
            "не_подтверждено": resource_statuses["unverified"],
        }
        for field, expected in compatibility_counts.items():
            if resources.get("meta", {}).get(field) != expected:
                errors.append(f"ST: meta.{field} mismatch")

    if contract or human_datasets:
        errors.extend(
            _validate_scientific_artifacts(
                contract, human_datasets, canonical_ids, set(resource_ids), vocab
            )
        )

    if novelty or concept or search_protocol:
        errors.extend(
            validate_novelty_artifacts(
                novelty, concept, search_protocol, canonical_ids, set(resource_ids)
            )
        )
        current_completeness = completeness_summary(
            [item for item in sources if isinstance(item, dict)]
        )
        if completeness.get("records") != len(sources):
            errors.append("completeness report: record count mismatch")
        if completeness.get("unresolved_count") != current_completeness["unresolved_count"]:
            errors.append("completeness report: unresolved count mismatch")
        if completeness.get("states") != current_completeness["states"]:
            errors.append("completeness report: state counters mismatch")
        if current_completeness["unresolved_count"]:
            errors.append("completeness report: unresolved source fields remain")

    review_ledger_path = root / "evidence-review-ledger.json"
    if review_ledger_path.is_file():
        try:
            review_ledger = load_json(review_ledger_path)
            review_entries = review_ledger.get("entries")
            if not isinstance(review_entries, dict) or review_ledger.get("meta", {}).get(
                "entry_count"
            ) != len(review_entries):
                errors.append("evidence review ledger: entry count mismatch")
            else:
                for name, entry in review_entries.items():
                    if (
                        not isinstance(name, str)
                        or not re.fullmatch(r"[A-Za-z0-9_-]+\.json", name)
                        or not isinstance(entry, dict)
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", str(entry.get("sha256_original", ""))
                        )
                        or not isinstance(entry.get("review"), dict)
                    ):
                        errors.append(f"evidence review ledger: malformed entry {name}")
        except (DataError, AttributeError) as exc:
            errors.append(f"evidence review ledger: {exc}")

    manifest_count = 0
    for manifest_path in sorted((root / "archive").glob("*/manifest.json")):
        manifest_count += 1
        try:
            manifest = load_json(manifest_path)
        except DataError as exc:
            errors.append(str(exc))
            continue
        for entry in manifest.get("files", []):
            path = manifest_path.parent / entry.get("name", "")
            if not path.is_file():
                errors.append(f"snapshot: missing {path}")
            elif sha256(path) != entry.get("sha256"):
                errors.append(f"snapshot: hash mismatch for {path}")

    unverified = sum(
        source.get("validation", {}).get("status") == "unverified" for source in sources
    )
    if unverified:
        warnings.append(f"{unverified} source records remain unverified")
    pending_screening = sum(
        source.get("validation", {}).get("screening_status") == "pending" for source in sources
    )
    if pending_screening:
        warnings.append(f"{pending_screening} source records await screening")

    counts = {
        "sources": len(sources),
        "aliases": len(alias_map),
        "active_clusters": len(active_clusters),
        "retired_clusters": len(clusters.get("retired_clusters", [])),
        "resources": len(resource_items),
        "archive_manifests": manifest_count,
        "novelty_variants": len(novelty.get("variants", [])),
        "unresolved_fields": (
            completeness.get("unresolved_count") if completeness else None
        ),
    }
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts}
