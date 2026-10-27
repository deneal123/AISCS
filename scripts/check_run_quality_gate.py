"""Validate the paired, data-free S26 run-quality manifests.

The agents and backend test suites deliberately have separate Python environments.  This
small stdlib-only gate keeps their shared terminal/privacy contract versioned without
making either service import the other one.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTS_MANIFEST = ROOT / "agents" / "tests" / "fixtures" / "run_quality_s16.json"
BACKEND_MANIFEST = ROOT / "backend" / "tests" / "fixtures" / "run_quality_s16.json"
VERSION_RE = re.compile(r"^s\d+-v\d+$")
ID_RE = re.compile(r"^[a-z0-9_]+$")
_SHARED_CONTRACTS = {
    "first_valid_result",
    "error_before_result_recovery",
    "post_terminal_discard",
    "privacy_boundary",
    "malformed_event_drop",
    "crash_redelivery_single_billing",
}
_REQUIRED_AGENT_SCENARIOS = {
    "auto_mode_confirmation",
    "s17_auto_mode_policy_privacy",
    "catalog_selection_and_revalidation",
    "s11_static_under_fifteen",
    "s11_enforce_reselection",
    "s11_observe",
    "s11_selector_fallbacks",
    "s12_mcp_resilience",
    "s13_safe_dedup_and_retry",
    "round_cap_and_deadline_finalization",
    "s25_ledger_native_receipts",
    "s25_grounding_repair_latch",
    "s26_provider_qualification_and_pinning",
    "s26_stream_privacy_and_single_receipt",
}
_REQUIRED_BACKEND_SCENARIOS = {
    "first_valid_result",
    "error_before_result_recovery",
    "post_terminal_discard",
    "invalid_terminal_and_eof",
    "privacy_boundary",
    "s17_auto_mode_policy_privacy",
    "malformed_event_drop",
    "crash_redelivery_single_billing",
}
_SCENARIO_KEYS = {"id", "event_order", "statuses", "reasons", "counts", "budgets"}


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return payload


def _bounded_strings(value: Any, *, field: str, path: Path) -> None:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and len(item) <= 80 and ID_RE.fullmatch(item)
        for item in value
    ):
        raise ValueError(
            f"{path.relative_to(ROOT)}: {field} must contain bounded identifiers only"
        )


def _validate(path: Path, payload: dict[str, Any], required: set[str]) -> set[str]:
    if set(payload) != {"version", "cross_service_contracts", "scenarios"}:
        raise ValueError(f"{path.relative_to(ROOT)} has unsupported top-level fields")
    version = payload["version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError(f"{path.relative_to(ROOT)} has an invalid version")
    _bounded_strings(
        payload["cross_service_contracts"], field="cross_service_contracts", path=path
    )
    contracts = set(payload["cross_service_contracts"])
    if len(contracts) != len(payload["cross_service_contracts"]):
        raise ValueError(f"{path.relative_to(ROOT)} repeats a cross-service contract")
    scenarios = payload["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"{path.relative_to(ROOT)} must declare scenarios")
    ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not set(scenario).issubset(_SCENARIO_KEYS):
            raise ValueError(
                f"{path.relative_to(ROOT)} has an unsupported scenario field"
            )
        identifier = scenario.get("id")
        if (
            not isinstance(identifier, str)
            or not ID_RE.fullmatch(identifier)
            or identifier in ids
        ):
            raise ValueError(
                f"{path.relative_to(ROOT)} has a duplicate or unsafe scenario id"
            )
        ids.add(identifier)
        for field in ("event_order", "statuses", "reasons"):
            if field in scenario:
                _bounded_strings(scenario[field], field=field, path=path)
        for field in ("counts", "budgets"):
            value = scenario.get(field, {})
            if not isinstance(value, dict) or not all(
                isinstance(key, str)
                and ID_RE.fullmatch(key)
                and type(amount) is int
                and amount >= 0
                for key, amount in value.items()
            ):
                raise ValueError(
                    f"{path.relative_to(ROOT)}: {field} must contain bounded integers"
                )
    missing = required - ids
    if missing:
        raise ValueError(
            f"{path.relative_to(ROOT)} misses required scenarios: {sorted(missing)}"
        )
    return ids


def main() -> int:
    agents = _load(AGENTS_MANIFEST)
    backend = _load(BACKEND_MANIFEST)
    agent_ids = _validate(AGENTS_MANIFEST, agents, _REQUIRED_AGENT_SCENARIOS)
    backend_ids = _validate(BACKEND_MANIFEST, backend, _REQUIRED_BACKEND_SCENARIOS)
    if agents["version"] != backend["version"]:
        raise ValueError(
            "agents and backend run-quality manifests use different versions"
        )
    if set(agents["cross_service_contracts"]) != _SHARED_CONTRACTS:
        raise ValueError(
            "agents manifest has an incomplete shared terminal/privacy contract"
        )
    if set(backend["cross_service_contracts"]) != _SHARED_CONTRACTS:
        raise ValueError(
            "backend manifest has an incomplete shared terminal/privacy contract"
        )
    print(
        f"run quality gate {agents['version']}: "
        f"agents={len(agent_ids)} backend={len(backend_ids)} shared={len(_SHARED_CONTRACTS)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"run quality gate failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
