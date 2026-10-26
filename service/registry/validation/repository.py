"""Blocking integrity gate over the whole registry."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...common.errors import DataError
from ...common.hashing import sha256
from ...common.jsonio import load_json
from ..completeness import RESOLUTION_STATES, completeness_summary
from ..layout import data_path
from ..novelty import validate_novelty_artifacts
from .audits import (
    load_required,
    validate_drosophila_connectome_audit,
    validate_ecap_scs_audit,
    validate_human_ecap_access_audit,
    validate_ns06_prior_art_audit,
    validate_resolution_audit,
)
from .records import LEGACY_FIELDS, validate_source_record
from .scientific import validate_scientific_artifacts


def validate_repository(root: Path | str, *, legacy: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    records = load_required(root, "records.json", errors, legacy=legacy)
    clusters = load_required(root, "clusters.json", errors, legacy=legacy)
    resources = load_required(root, "ST.json", errors, legacy=legacy)
    aliases = load_required(root, "aliases.json", errors, legacy=legacy)
    schema = load_required(root, "source-record.schema.json", errors, legacy=legacy)
    vocab = load_required(root, "vocabularies.json", errors, legacy=legacy)
    contract_path = data_path(root, "scientific-contract.json", legacy=legacy)
    matrix_path = data_path(root, "human-dataset-matrix.json", legacy=legacy)
    novelty_path = data_path(root, "novelty-landscape.json", legacy=legacy)
    concept_path = data_path(root, "dissertation-concept.json", legacy=legacy)
    search_path = data_path(root, "search-protocol.json", legacy=legacy)
    runtime_path = data_path(root, "runtime-audit.json", legacy=legacy)
    ecap_scs_audit_path = data_path(root, "ecap-scs-audit.json", legacy=legacy)
    connectome_audit_path = data_path(root, "drosophila-connectome-audit.json", legacy=legacy)
    nociception_audit_path = data_path(root, "drosophila-nociception-audit.json", legacy=legacy)
    synthetic_audit_path = data_path(root, "synthetic-domain-audit.json", legacy=legacy)
    ns06_audit_path = data_path(root, "ns06-prior-art-audit.json", legacy=legacy)
    scs_outcome_audit_path = data_path(root, "scs-outcome-audit.json", legacy=legacy)
    ns11_audit_path = data_path(root, "ns11-prediction-audit.json", legacy=legacy)
    human_ecap_access_path = data_path(root, "human-ecap-scs-access-audit.json", legacy=legacy)
    has_scientific_artifacts = contract_path.is_file() or matrix_path.is_file()
    if (root / "staging").is_dir() or has_scientific_artifacts:
        contract = load_required(root, "scientific-contract.json", errors, legacy=legacy)
        human_datasets = load_required(root, "human-dataset-matrix.json", errors, legacy=legacy)
    else:
        contract = {}
        human_datasets = {}
    has_novelty_artifacts = (
        novelty_path.is_file() or concept_path.is_file() or search_path.is_file()
    )
    if has_novelty_artifacts:
        novelty = load_required(root, "novelty-landscape.json", errors, legacy=legacy)
        concept = load_required(root, "dissertation-concept.json", errors, legacy=legacy)
        search_protocol = load_required(root, "search-protocol.json", errors, legacy=legacy)
        completeness = load_required(root, "completeness-report.json", errors, legacy=legacy)
        runtime_audit = load_required(root, runtime_path.name, errors, legacy=legacy)
        ecap_scs_audit = (
            load_required(root, ecap_scs_audit_path.name, errors, legacy=legacy)
            if ecap_scs_audit_path.is_file()
            else {}
        )
        connectome_audit = (
            load_required(root, connectome_audit_path.name, errors, legacy=legacy)
            if connectome_audit_path.is_file()
            else {}
        )
        nociception_audit = (
            load_required(root, nociception_audit_path.name, errors, legacy=legacy)
            if nociception_audit_path.is_file()
            else {}
        )
        synthetic_audit = (
            load_required(root, synthetic_audit_path.name, errors, legacy=legacy)
            if synthetic_audit_path.is_file()
            else {}
        )
        ns06_audit = (
            load_required(root, ns06_audit_path.name, errors, legacy=legacy)
            if ns06_audit_path.is_file()
            else {}
        )
        scs_outcome_audit = (
            load_required(root, scs_outcome_audit_path.name, errors, legacy=legacy)
            if scs_outcome_audit_path.is_file()
            else {}
        )
        ns11_audit = (
            load_required(root, ns11_audit_path.name, errors, legacy=legacy)
            if ns11_audit_path.is_file()
            else {}
        )
        human_ecap_access = (
            load_required(root, human_ecap_access_path.name, errors, legacy=legacy)
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
        errors.extend(validate_ecap_scs_audit(ecap_scs_audit, canonical_ids))
    if connectome_audit:
        errors.extend(validate_drosophila_connectome_audit(connectome_audit, canonical_ids))
    if nociception_audit:
        errors.extend(
            validate_resolution_audit(
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
        errors.extend(validate_human_ecap_access_audit(human_ecap_access, canonical_ids))
    if synthetic_audit:
        errors.extend(
            validate_resolution_audit(
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
        errors.extend(validate_ns06_prior_art_audit(ns06_audit, canonical_ids, variant_ids))
    if scs_outcome_audit:
        errors.extend(
            validate_resolution_audit(
                scs_outcome_audit,
                canonical_ids,
                label="SCS outcome audit",
                dimensions={"input_role", "target_role", "study_design", "prognostic_validation"},
            )
        )
    if ns11_audit:
        errors.extend(
            validate_resolution_audit(
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
            validate_scientific_artifacts(
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

    review_ledger_path = data_path(root, "evidence-review-ledger.json", legacy=legacy)
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
