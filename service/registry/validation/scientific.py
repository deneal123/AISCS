"""Cross-checks of the scientific contract and evidence artifacts."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def validate_scientific_artifacts(
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
