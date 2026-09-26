"""Validation and bounded search views for the Drosophila x SCS novelty artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .core import load_json

PRIOR_ART_OUTCOMES = frozenset(
    {"direct_analogue_found", "partial_analogues_only", "no_direct_analogue_found_at_cutoff"}
)
REQUIRED_AXES = (
    "drosophila_model",
    "observation",
    "perturbation",
    "bridge_mechanism",
    "scs_task",
    "validation_level",
)


def validate_novelty_artifacts(
    landscape: dict[str, Any],
    concept: dict[str, Any],
    search_protocol: dict[str, Any],
    canonical_ids: set[str],
    resource_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if landscape.get("meta", {}).get("schema_version") != "1.0.0":
        errors.append("novelty landscape: unsupported schema version")
    axes = landscape.get("morphological_matrix", {}).get("axes", {})
    if set(axes) != set(REQUIRED_AXES) or any(not axes.get(name) for name in REQUIRED_AXES):
        errors.append("novelty landscape: incomplete morphological matrix")
    expected_raw = 1
    for name in REQUIRED_AXES:
        expected_raw *= len(axes.get(name, []))
    if landscape.get("morphological_matrix", {}).get("raw_combinations_count") != expected_raw:
        errors.append("novelty landscape: raw combination count mismatch")
    variants = landscape.get("variants", [])
    variant_ids = [item.get("id") for item in variants if isinstance(item, dict)]
    if not variants or len(variant_ids) != len(set(variant_ids)):
        errors.append("novelty landscape: variants must be non-empty and uniquely identified")
    forbidden_keys = {"rank", "score", "confidence", "evidence_grade", "strength"}
    search_ids = {
        item.get("id")
        for item in search_protocol.get("search_streams", [])
        if isinstance(item, dict)
    }
    for stream in search_protocol.get("search_streams", []):
        if not isinstance(stream, dict):
            continue
        source_ids = stream.get("source_ids", [])
        if (
            not isinstance(source_ids, list)
            or any(not isinstance(source_id, str) for source_id in source_ids)
            or len(source_ids) != len(set(source_ids))
        ):
            errors.append(f"search stream: duplicate or invalid source IDs in {stream.get('id')}")
            continue
        for source_id in source_ids:
            if source_id not in canonical_ids:
                errors.append(
                    f"search stream: missing canonical source {source_id} "
                    f"in {stream.get('id')}"
                )
    for variant in variants:
        variant_id = variant.get("id")
        if forbidden_keys & set(variant):
            errors.append(f"novelty landscape: ranked field in {variant_id}")
        if variant.get("prior_art_outcome") not in PRIOR_ART_OUTCOMES:
            errors.append(f"novelty landscape: invalid prior-art outcome in {variant_id}")
        for axis in REQUIRED_AXES:
            values = variant.get("axes", {}).get(axis, [])
            if isinstance(values, str):
                values = [values]
            if not values or not set(values) <= set(axes.get(axis, [])):
                errors.append(f"novelty landscape: invalid {axis} in {variant_id}")
        bridge = str(variant.get("bridge", "")).casefold()
        if "drosophila" not in bridge or "ecap" not in bridge or "scs" not in bridge:
            errors.append(f"novelty landscape: incomplete two-model bridge in {variant_id}")
        if not variant.get("falsification_experiment"):
            errors.append(f"novelty landscape: no falsification experiment in {variant_id}")
        refs = variant.get("closest_analogue_refs", [])
        for ref in refs:
            if ref.startswith("ST") and ref not in resource_ids:
                errors.append(f"novelty landscape: missing resource {ref} in {variant_id}")
            elif ref.startswith("S") and not ref.startswith("ST") and ref not in canonical_ids:
                errors.append(f"novelty landscape: missing source {ref} in {variant_id}")
        if not set(variant.get("search_trace_ids", [])) <= search_ids:
            errors.append(f"novelty landscape: missing search trace in {variant_id}")

    if concept.get("meta", {}).get("gate") != "G0_REVISE":
        errors.append("dissertation concept: gate must remain G0_REVISE")
    if concept.get("architecture", {}).get("id") != "ARCH-DROSOPHILA-ECAP-SCS-01":
        errors.append("dissertation concept: fixed two-model architecture missing")
    if concept.get("hypothesis", {}).get("id") != "H-DES-01":
        errors.append("dissertation concept: exactly one umbrella hypothesis required")
    for collection in ("actuality", "novelty_claims", "defense_propositions"):
        for claim in concept.get(collection, []):
            for ref in claim.get("source_refs", []):
                if ref.startswith("ST") and ref not in resource_ids:
                    errors.append(f"dissertation concept: missing resource {ref}")
                elif ref.startswith("S") and not ref.startswith("ST") and ref not in canonical_ids:
                    errors.append(f"dissertation concept: missing source {ref}")
            if not claim.get("locator_refs"):
                errors.append(f"dissertation concept: {claim.get('id')} lacks locator refs")
    forbidden_claims = " ".join(concept.get("forbidden_claims", [])).casefold()
    for token in ("subjective human pain", "direct digital twin", "direct measure of pain"):
        if token not in forbidden_claims:
            errors.append(f"dissertation concept: missing forbidden boundary {token}")
    return errors


def novelty_summary(data_dir: Any) -> dict[str, Any]:
    landscape = load_json(data_dir / "novelty-landscape.json")
    variants = landscape.get("variants", [])
    outcomes: dict[str, int] = {}
    for item in variants:
        outcome = item.get("prior_art_outcome", "missing")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {
        "meta": deepcopy(landscape.get("meta", {})),
        "morphological_matrix": deepcopy(landscape.get("morphological_matrix", {})),
        "variant_count": len(variants),
        "prior_art_outcomes": dict(sorted(outcomes.items())),
    }


def search_novelty(
    data_dir: Any,
    *,
    query: str | None = None,
    prior_art_outcome: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    landscape = load_json(data_dir / "novelty-landscape.json")
    needle = query.casefold().strip() if query else ""
    items: list[dict[str, Any]] = []
    for item in landscape.get("variants", []):
        if prior_art_outcome and item.get("prior_art_outcome") != prior_art_outcome:
            continue
        if needle and needle not in str(item).casefold():
            continue
        items.append(deepcopy(item))
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }
