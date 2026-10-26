"""Schema-2 completeness helpers for terminally resolved source fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

RESOLUTION_STATES = frozenset(
    {"reported", "not_reported", "not_applicable", "unavailable_after_search"}
)

RESOLVED_PATHS = (
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
    "identifiers.doi",
    "identifiers.pmid",
    "identifiers.arxiv_id",
    "identifiers.patent_id",
    "identifiers.dataset_id",
    "identifiers.exact_url",
    "provenance.retrieved_at",
    "provenance.search_stream",
    "provenance.query_or_seed",
    "provenance.iteration",
    "evidence.species",
    "evidence.population",
    "evidence.subject_domain",
    "evidence.modalities",
    "evidence.sample_size",
    "evidence.target_construct",
    "evidence.target_label",
    "evidence.access_status",
    "validation.checked_at",
    "validation.split_unit",
    "validation.cross_subject",
    "validation.external_validation",
    "validation.calibration",
    "validation.uncertainty",
    "validation.exclusion_reason",
    "validation.notes",
)

FORBIDDEN_PLACEHOLDERS = frozenset({"", "unknown", "todo", "tbd", "не указано"})
TERMINAL_MARKERS = RESOLUTION_STATES - {"reported"}


def get_path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def set_path(record: dict[str, Any], path: str, value: Any) -> None:
    target: dict[str, Any] = record
    parts = path.split(".")
    for part in parts[:-1]:
        nested = target.setdefault(part, {})
        if not isinstance(nested, dict):
            raise ValueError(f"cannot set nested path {path}")
        target = nested
    target[parts[-1]] = value


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in FORBIDDEN_PLACEHOLDERS


def _default_state(record: dict[str, Any], path: str, value: Any) -> str:
    if isinstance(value, str) and value in TERMINAL_MARKERS:
        return value
    if value is not None and not is_placeholder(value) and value != []:
        return "reported"
    if record.get("validation", {}).get("status") == "rejected":
        return "unavailable_after_search"
    if path.startswith("identifiers.") and path != "identifiers.exact_url":
        return "not_applicable"
    if path == "validation.exclusion_reason":
        return "not_applicable"
    if record.get("validation", {}).get("full_text_status") == "checked":
        return "not_reported"
    return "unavailable_after_search"


def _reason(record: dict[str, Any], path: str, state: str) -> str:
    if state == "reported":
        return "Значение сохранено из проверенной канонической карточки."
    if state == "not_reported":
        return "Свойство не сообщено в проверенном первичном тексте."
    if state == "not_applicable":
        return "Поле неприменимо к типу и роли данного источника."
    if record.get("validation", {}).get("status") == "rejected":
        return (
            "Источник закрыт терминальным решением rejected; "
            "методическая экстракция не выполняется."
        )
    return (
        "Значение не удалось установить по доступному первичному или библиографическому "
        "источнику; отсутствие зафиксировано без догадки."
    )


def _locator(record: dict[str, Any], path: str) -> dict[str, str]:
    exact_url = record.get("identifiers", {}).get("exact_url")
    return {
        "url": exact_url or "local:validation-log",
        "locator": f"canonical field {path}",
    }


def migrate_record(record: dict[str, Any], *, checked_at: str) -> dict[str, Any]:
    """Return a schema-2 record with a terminal resolution for every nullable field."""
    migrated = deepcopy(record)
    resolutions: dict[str, Any] = {}
    for path in RESOLVED_PATHS:
        value = get_path(migrated, path)
        state = _default_state(migrated, path, value)
        if isinstance(value, str) and value in TERMINAL_MARKERS:
            state = value
            value = None
        elif is_placeholder(value):
            set_path(migrated, path, "unavailable_after_search")
            value = None
            state = "unavailable_after_search"
        elif value == []:
            state = "not_applicable" if path == "evidence.modalities" else state
        resolutions[path] = {
            "state": state,
            "value": deepcopy(value) if state == "reported" else None,
            "reason": _reason(migrated, path, state),
            "checked_at": checked_at,
            "locators": [_locator(migrated, path)],
        }
    migrated["field_resolution"] = resolutions
    return migrated


def validate_resolutions(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source_id = str(record.get("id", "<missing>"))
    resolutions = record.get("field_resolution")
    if not isinstance(resolutions, dict):
        return [f"{source_id}: field_resolution must be an object"]
    missing = set(RESOLVED_PATHS) - set(resolutions)
    extra = set(resolutions) - set(RESOLVED_PATHS)
    if missing:
        errors.append(f"{source_id}: unresolved fields {sorted(missing)}")
    if extra:
        errors.append(f"{source_id}: unexpected field resolutions {sorted(extra)}")
    for path in RESOLVED_PATHS:
        item = resolutions.get(path)
        if not isinstance(item, dict):
            continue
        state = item.get("state")
        value = item.get("value")
        if state not in RESOLUTION_STATES:
            errors.append(f"{source_id}: invalid resolution state for {path}: {state!r}")
        if state == "reported" and (value is None or is_placeholder(value) or value == []):
            errors.append(f"{source_id}: reported resolution lacks value for {path}")
        if state != "reported" and value is not None:
            errors.append(f"{source_id}: terminal resolution must have null value for {path}")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            errors.append(f"{source_id}: resolution lacks reason for {path}")
        if not isinstance(item.get("checked_at"), str) or not item["checked_at"]:
            errors.append(f"{source_id}: resolution lacks checked_at for {path}")
        locators = item.get("locators")
        if not isinstance(locators, list) or not locators:
            errors.append(f"{source_id}: resolution lacks locators for {path}")
        elif any(
            not isinstance(locator, dict)
            or not locator.get("url")
            or not locator.get("locator")
            for locator in locators
        ):
            errors.append(f"{source_id}: invalid resolution locator for {path}")
        current = get_path(record, path)
        if is_placeholder(current):
            errors.append(f"{source_id}: forbidden placeholder remains in {path}")
        if state == "reported" and current != value:
            errors.append(f"{source_id}: resolution value mismatch for {path}")
    return errors


def completeness_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    states = {state: 0 for state in sorted(RESOLUTION_STATES)}
    unresolved: list[dict[str, str]] = []
    for record in records:
        errors = validate_resolutions(record)
        unresolved.extend({"source_id": record.get("id", ""), "error": error} for error in errors)
        for item in record.get("field_resolution", {}).values():
            state = item.get("state") if isinstance(item, dict) else None
            if state in states:
                states[state] += 1
    return {
        "records": len(records),
        "resolved_fields": sum(states.values()),
        "states": states,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
