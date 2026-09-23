"""Typed loader for the local, versioned transport protocol manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProtocolManifest:
    version: str
    run_input_fields: frozenset[str]
    run_result_fields: frozenset[str]
    required_result_fields: frozenset[str]
    terminal_keys: frozenset[str]
    event_types: frozenset[str]
    websocket_frames: frozenset[str]
    error_codes: frozenset[str]
    error_categories: frozenset[str]
    status_families: frozenset[str]
    auto_reason_codes: frozenset[str]
    usage_kinds: frozenset[str]
    usage_integrity_reasons: frozenset[str]
    provider_catalog_sources: frozenset[str]
    provider_catalog_statuses: frozenset[str]
    provider_capability_evidence_sources: frozenset[str]
    provider_qualification_statuses: frozenset[str]
    provider_model_capabilities: frozenset[str]
    provider_operations: frozenset[str]
    provider_admission_statuses: frozenset[str]
    provider_generation_statuses: frozenset[str]
    grounding_states: frozenset[str]
    grounding_reasons: frozenset[str]
    tool_outcomes: frozenset[str]
    run_integrity_reasons: frozenset[str]
    run_phases: tuple[str, ...]
    stream_protocol_stages: frozenset[str]
    workspace_operation_statuses: frozenset[str]
    work_snapshot_version: int


def _strings(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"invalid protocol manifest field: {field}")
    return frozenset(value)


def _ordered_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"invalid protocol manifest field: {field}")
    return tuple(value)


@lru_cache(maxsize=1)
def load_protocol_manifest() -> ProtocolManifest:
    path = Path(__file__).with_name("protocol_manifest.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("run"), dict):
        raise RuntimeError("invalid protocol manifest root")
    run = raw["run"]
    version = raw.get("version")
    work_version = raw.get("work_snapshot_version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("invalid protocol manifest version")
    if not isinstance(work_version, int) or work_version < 1:
        raise RuntimeError("invalid Work snapshot version")
    return ProtocolManifest(
        version=version,
        run_input_fields=_strings(run.get("input_fields"), "run.input_fields"),
        run_result_fields=_strings(run.get("result_fields"), "run.result_fields"),
        required_result_fields=_strings(
            run.get("required_result_fields"), "run.required_result_fields"
        ),
        terminal_keys=_strings(run.get("terminal_keys"), "run.terminal_keys"),
        event_types=_strings(raw.get("events"), "events"),
        websocket_frames=_strings(raw.get("websocket_frames"), "websocket_frames"),
        error_codes=_strings(raw.get("error_codes"), "error_codes"),
        error_categories=_strings(raw.get("error_categories"), "error_categories"),
        status_families=_strings(raw.get("status_families"), "status_families"),
        auto_reason_codes=_strings(raw.get("auto_reason_codes"), "auto_reason_codes"),
        usage_kinds=_strings(raw.get("usage_kinds"), "usage_kinds"),
        usage_integrity_reasons=_strings(
            raw.get("usage_integrity_reasons"), "usage_integrity_reasons"
        ),
        provider_catalog_sources=_strings(
            raw.get("provider_catalog_sources"), "provider_catalog_sources"
        ),
        provider_catalog_statuses=_strings(
            raw.get("provider_catalog_statuses"), "provider_catalog_statuses"
        ),
        provider_capability_evidence_sources=_strings(
            raw.get("provider_capability_evidence_sources"),
            "provider_capability_evidence_sources",
        ),
        provider_qualification_statuses=_strings(
            raw.get("provider_qualification_statuses"), "provider_qualification_statuses"
        ),
        provider_model_capabilities=_strings(
            raw.get("provider_model_capabilities"), "provider_model_capabilities"
        ),
        provider_operations=_strings(raw.get("provider_operations"), "provider_operations"),
        provider_admission_statuses=_strings(
            raw.get("provider_admission_statuses"), "provider_admission_statuses"
        ),
        provider_generation_statuses=_strings(
            raw.get("provider_generation_statuses"), "provider_generation_statuses"
        ),
        grounding_states=_strings(raw.get("grounding_states"), "grounding_states"),
        grounding_reasons=_strings(raw.get("grounding_reasons"), "grounding_reasons"),
        tool_outcomes=_strings(raw.get("tool_outcomes"), "tool_outcomes"),
        run_integrity_reasons=_strings(raw.get("run_integrity_reasons"), "run_integrity_reasons"),
        run_phases=_ordered_strings(raw.get("run_phases"), "run_phases"),
        stream_protocol_stages=_strings(
            raw.get("stream_protocol_stages"), "stream_protocol_stages"
        ),
        workspace_operation_statuses=_strings(
            raw.get("workspace_operation_statuses"), "workspace_operation_statuses"
        ),
        work_snapshot_version=work_version,
    )


__all__ = ["ProtocolManifest", "load_protocol_manifest"]
