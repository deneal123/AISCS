"""Validators of thematic audit artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...common.errors import DataError
from ...common.jsonio import load_json
from ..layout import data_path


def load_required(
    root: Path, name: str, errors: list[str], *, legacy: bool = False,
) -> dict[str, Any]:
    try:
        return load_json(data_path(root, name, legacy=legacy))
    except DataError as exc:
        errors.append(str(exc))
        return {}


def validate_ecap_scs_audit(
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


def validate_drosophila_connectome_audit(
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


def validate_human_ecap_access_audit(
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


def validate_resolution_audit(
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


def validate_ns06_prior_art_audit(
    audit: dict[str, Any], canonical_ids: set[str], variant_ids: set[str]
) -> list[str]:
    label = "NS-06 prior-art audit"
    errors: list[str] = []
    if audit.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append(f"{label}: unsupported schema version")
    status = audit.get("meta", {}).get("status")
    if status not in {"open", "terminal_stop_at_cutoff"}:
        errors.append(f"{label}: unsupported status")
    if status == "terminal_stop_at_cutoff":
        disposition = audit.get("operational_disposition", {})
        if (disposition.get("decision") != "STOP at the documented 2026-09-26 cutoff"
                or disposition.get("saturation") is not False
                or not disposition.get("unresolved_scope")
                or not disposition.get("prohibited_inferences")
                or not disposition.get("primary_routes")):
            errors.append(
                f"{label}: terminal STOP lacks cutoff, routes, unresolved scope, or claim boundary"
            )
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
