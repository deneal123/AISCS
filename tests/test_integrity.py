import shutil
from copy import deepcopy
from pathlib import Path

from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_current_repository_passes_integrity_gate() -> None:
    report = validate_repository(DATA)
    assert report["ok"], report["errors"]
    assert report["counts"] | {"archive_manifests": 0} == {
        "sources": len(load_json(DATA / "records.json")["sources"]),
        "aliases": 271,
        "active_clusters": 43,
        "retired_clusters": 11,
        "resources": 109,
        "archive_manifests": 0,
        "novelty_variants": 15,
        "unresolved_fields": 0,
    }
    assert report["counts"]["archive_manifests"] == len(
        list((DATA / "archive").glob("*/manifest.json"))
    )
    assert report["counts"]["archive_manifests"] <= 4


def test_schema_1_2_validated_the_pre_deduplication_350_record_snapshot() -> None:
    snapshot = ROOT / "tests" / "fixtures" / "history" / "archive" / "2026-09-22T102852Z-pre-batch-001"
    report = validate_repository(snapshot)
    assert report["ok"], report["errors"]
    assert report["counts"]["sources"] == 350
    assert report["counts"]["novelty_variants"] == 0


def test_evidence_review_ledger_rejects_missing_entry(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for path in DATA.glob("*.json"):
        shutil.copy2(path, data / path.name)
    ledger = load_json(data / "evidence-review-ledger.json")
    ledger["entries"].pop(next(iter(ledger["entries"])))
    atomic_write_json(data / "evidence-review-ledger.json", ledger)
    report = validate_repository(data)
    assert "evidence review ledger: entry count mismatch" in report["errors"]


def test_integrity_rejects_duplicate_stable_identifier(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for path in DATA.glob("*.json"):
        shutil.copy2(path, data / path.name)
    records = load_json(DATA / "records.json")
    duplicate = deepcopy(records["sources"][1])
    duplicate["id"] = "S999999"
    duplicate["identifiers"]["doi"] = records["sources"][0]["identifiers"]["doi"]
    duplicate["field_resolution"]["identifiers.doi"]["value"] = duplicate[
        "identifiers"
    ]["doi"]

    records["sources"].append(duplicate)
    records["meta"]["records_count"] += 1
    atomic_write_json(data / "records.json", records)

    report = validate_repository(data)

    assert not report["ok"]
    assert any("duplicate doi" in error for error in report["errors"])


def test_integrity_rejects_unclustered_decision_for_clustered_source(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for path in DATA.glob("*.json"):
        shutil.copy2(path, data / path.name)
    clusters = load_json(data / "clusters.json")
    source_id = clusters["clusters"][0]["состав_кластера"][0]
    clusters["unclustered_decisions"][source_id] = {
        "decision": "no_cluster_applicable",
        "checked_at": "2026-09-25",
        "reason": "Deliberate contradiction for the integrity test.",
    }
    atomic_write_json(data / "clusters.json", clusters)

    report = validate_repository(data)

    assert not report["ok"]
    assert any(
        "unclustered_decisions reference clustered or unknown records" in error
        and source_id in error
        for error in report["errors"]
    )


def test_integrity_rejects_stale_cluster_representative(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for path in DATA.glob("*.json"):
        shutil.copy2(path, data / path.name)
    clusters = load_json(data / "clusters.json")
    representative = clusters["clusters"][0]["представитель"]
    representative["validation"]["notes"] = "Stale embedded copy"
    atomic_write_json(data / "clusters.json", clusters)

    report = validate_repository(data)

    assert any("clusters: stale representative in" in error for error in report["errors"])


def test_ecap_scs_audit_resolves_the_five_measurement_dimensions() -> None:
    audit = load_json(DATA / "ecap-scs-audit.json")
    records = {
        source["id"]: source for source in load_json(DATA / "records.json")["sources"]
    }
    expected_dimensions = {
        "sample",
        "electrode_geometry",
        "stimulation",
        "split_unit",
        "metrics",
    }

    assert audit["meta"]["records_count"] == len(audit["entries"])
    assert len(audit["entries"]) >= 15
    assert "not a direct pain measure" in audit["construct_boundary"]
    for entry in audit["entries"]:
        assert entry["source_id"] in records
        assert set(entry["extraction"]) == expected_dimensions
        for item in entry["extraction"].values():
            assert item["state"] in {
                "reported",
                "not_reported",
                "not_applicable",
                "unavailable_after_search",
            }
            assert item["checked_at"] in {"2026-09-24", "2026-09-25"}
            assert item["reason"]
            assert item["locators"]
            assert all(locator["url"] and locator["locator"] for locator in item["locators"])


def test_ecap_scs_audit_preserves_construct_and_validation_boundaries() -> None:
    audit = load_json(DATA / "ecap-scs-audit.json")
    entries = {entry["source_id"]: entry for entry in audit["entries"]}
    records = {
        source["id"]: source for source in load_json(DATA / "records.json")["sources"]
    }

    assert entries["S105"]["extraction"]["sample"]["value"] == "8 chronic-pain participants"
    assert "42 participants" in entries["S239"]["extraction"]["sample"]["value"]
    assert records["S239"]["evidence"]["target_construct"] == "clinical_function"
    assert records["S162"]["evidence"]["target_construct"] == "technical_signal_quality"
    assert "neither study collected baseline pain characteristics" in records["S162"]["validation"]["notes"]
    assert "15 selected" in entries["S360"]["extraction"]["sample"]["value"]
    assert records["S360"]["evidence"]["target_construct"] == "scs_response"
    assert "six swine" in entries["S363"]["extraction"]["sample"]["value"]
    assert "animal_to_human_transfer_unvalidated" in records["S363"]["risk_flags"]


def test_connectome_audit_separates_anatomy_dynamics_and_comparators() -> None:
    audit = load_json(DATA / "drosophila-connectome-audit.json")
    entries = {entry["source_id"]: entry["extraction"] for entry in audit["entries"]}
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}

    assert set(entries) == {
        "S068", "S106", "S219", "S286", "S320", "S738", "S739", "S740",
        "S741", "S743", "S744", "S763", "S773", "S774", "S775", "S782", "S783",
    }
    assert audit["meta"]["records_count"] == len(entries)
    assert all(len(extraction) == 5 for extraction in entries.values())
    assert "v888" in entries["S738"]["connectome_version"]["value"]
    assert entries["S738"]["dynamic_model"]["state"] == "not_applicable"
    assert entries["S738"]["experimental_comparator"]["state"] == "not_reported"
    assert "v783" in entries["S739"]["connectome_version"]["value"]
    assert "v783" in entries["S068"]["connectome_version"]["value"]
    assert entries["S106"]["dynamic_model"]["state"] == "not_applicable"
    assert "not flies" in entries["S739"]["scope_boundary"]["value"]
    assert "Optogenetic" in entries["S740"]["experimental_comparator"]["value"]
    assert entries["S286"]["experimental_comparator"]["state"] == "not_applicable"
    assert "v783" in entries["S320"]["connectome_version"]["value"]
    assert entries["S320"]["experimental_comparator"]["state"] == "not_applicable"
    assert records["S320"]["validation"]["full_text_status"] == "checked"
    assert records["S320"]["evidence"]["sample_size"] == 2
    assert entries["S741"]["connectome_version"]["state"] == "not_reported"
    assert entries["S741"]["experimental_comparator"]["state"] == "not_applicable"
    assert entries["S743"]["experimental_comparator"]["state"] == "not_applicable"
    assert "fib25-fib19_v2.2.json" in entries["S744"]["connectome_version"]["value"]
    assert "MANC v1.2.3" in entries["S763"]["connectome_version"]["value"]
    assert entries["S773"]["dynamic_model"]["state"] == "not_applicable"
    assert entries["S774"]["connectome_version"]["state"] == "not_reported"
    assert entries["S775"]["dynamic_model"]["state"] == "reported"
    assert entries["S775"]["experimental_comparator"]["state"] == "reported"
    assert "snapshot 783" in entries["S782"]["connectome_version"]["value"]
    assert entries["S782"]["experimental_comparator"]["state"] == "reported"
    assert entries["S783"]["dynamic_model"]["state"] == "reported"
    assert "BANC v626" in entries["S763"]["connectome_version"]["value"]
    assert entries["S763"]["dynamic_model"]["state"] == "not_applicable"
    assert entries["S763"]["experimental_comparator"]["state"] == "reported"
    sapkal = next(entry for entry in audit["entries"] if entry["source_id"] == "S763")
    assert sapkal["relationship_to_s740"]["source_id"] == "S740"
    assert records["S763"]["validation"]["full_text_status"] == "checked"
    assert records["S219"]["evidence"]["subject_domain"] == "drosophila_adult"
    assert records["S740"]["evidence"]["target_construct"] == "not_applicable"
    walking = next(entry for entry in audit["entries"] if entry["source_id"] == "S740")
    assert {item["dataset"] for item in walking["input_matrix_artifacts"]} == {
        "MANC", "FANC", "mCNS", "BANC"
    }
    mcns = next(item for item in walking["input_matrix_artifacts"] if item["dataset"] == "mCNS")
    assert mcns["matrix"].endswith("W_20260210_vncRoisOnly.csv")
    assert "run_id=33241780/logs/run_config.yaml" in mcns["locator"]
    banc = next(item for item in walking["input_matrix_artifacts"] if item["dataset"] == "BANC")
    assert banc["matrix"].endswith("W_20260217.npz")
    assert "run_id=33241778/logs/run_config.yaml" in banc["locator"]
    assert "do not establish the upstream connectome release" in walking["input_matrix_note"]
    review = walking["upstream_provenance_review"]
    assert review["primary_full_text"]["url"].endswith("PMC13142387/fullTextXML")
    fanc_access = next(item for item in review["dataset_access"] if item["dataset"] == "FANC")
    assert fanc_access["annotation_table_versions"] == [
        "motor neuron table v7", "left t1 local premotor table v6"
    ]
    assert "not the FANC segmentation materialization" in fanc_access["version_boundary"]
    assert "not_reported" in review["decision"]
    assert {item["source_id"] for item in audit["screened_code_resources"]} == {
        "S200", "S292", "S737"
    }
    assert any(item["type"] == "code_for" and item["target_id"] == "S320"
               for item in records["S292"]["relations"])
    assert "22260924" in walking["simulation_archive"]["url"]
    for matrix in walking["input_matrix_artifacts"]:
        release = matrix["upstream_release"]
        assert release["state"] == "not_reported"
        assert release["value"] is None
        assert "2026-09-24" <= release["checked_at"] <= audit["meta"]["generated_at"]
        assert release["reason"]
        assert release["locators"]
        assert matrix["repository_file_last_change"]["commit_url"].startswith(
            "https://github.com/smpuglie/Pugliese_2026/commit/"
        )


def test_human_ecap_access_audit_requires_owner_confirmation(tmp_path: Path) -> None:
    audit = load_json(DATA / "human-ecap-scs-access-audit.json")
    entries = {item["trial_id"]: item for item in audit["candidates"]}
    assert len(entries) == len(audit["candidates"])
    assert {"NCT02924129", "NCT04319887", "NCT04938245", "NL7889"} <= set(entries)
    assert audit["meta"]["decision"] == "no_owner_confirmed_usable_dataset"
    assert entries["NCT02924129"]["checks"]["access_procedure"]["state"] == "conflicting"
    assert entries["NCT04319887"]["checks"]["access_procedure"]["state"] == "conflicting"
    assert entries["NCT04938245"]["checks"]["access_procedure"]["state"] == "partial"
    assert all(
        item["checks"]["ethics_secondary_use"]["state"] == "unconfirmed"
        for item in entries.values()
    )
    assert entries["NCT04938245"]["decision"] == "request_route_documented_release_not_located"
    assert entries["NL7889"]["source_refs"] == ["S793"]
    assert entries["NL7889"]["checks"]["patient_linkage"]["state"] == "unconfirmed"
    assert entries["NCT02924129"]["source_refs"] == ["S779", "S780", "S781"]
    assert entries["NCT04938245"]["owner_route_review_2026_09_25"]["sent"] is False
    assert not any(item["owner_confirmation_received"] for item in entries.values())

    data = tmp_path / "data"
    data.mkdir()
    for path in DATA.glob("*.json"):
        shutil.copy2(path, data / path.name)
    audit["candidates"][0]["checks"].pop("ethics_secondary_use")
    atomic_write_json(data / "human-ecap-scs-access-audit.json", audit)
    report = validate_repository(data)
    assert not report["ok"]
    assert any("requires exactly" in error for error in report["errors"])

    audit["candidates"][0]["checks"]["ethics_secondary_use"] = {
        "state": "unconfirmed",
        "finding": "Secondary-use ethics review is not established.",
        "locators": [{"url": "https://example.org", "locator": "test locator"}],
    }
    audit["candidates"][0]["decision"] = "usable"
    audit["meta"]["decision"] = "owner_confirmed_usable_dataset"
    atomic_write_json(data / "human-ecap-scs-access-audit.json", audit)
    report = validate_repository(data)
    assert not report["ok"]
    assert any("cannot be usable without owner confirmation" in error for error in report["errors"])

    eligible = deepcopy(load_json(DATA / "human-ecap-scs-access-audit.json"))
    candidate = eligible["candidates"][0]
    candidate["decision"] = "usable"
    candidate["owner_confirmation_received"] = True
    candidate["owner_confirmation_evidence"] = "Test-only owner confirmation fixture"
    for dimension, check in candidate["checks"].items():
        check["state"] = (
            "confirmed_by_institution" if dimension == "ethics_secondary_use" else "confirmed_by_owner"
        )
    eligible["meta"]["decision"] = "owner_confirmed_usable_dataset"
    atomic_write_json(data / "human-ecap-scs-access-audit.json", eligible)
    report = validate_repository(data)
    assert report["ok"], report["errors"]


def test_synthetic_domain_audit_tracks_real_data_and_external_test() -> None:
    audit = load_json(DATA / "synthetic-domain-audit.json")
    entries = {entry["source_id"]: entry["extraction"] for entry in audit["entries"]}
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}

    assert set(entries) == {
        "S035", "S083", "S084", "S088", "S149", "S192", "S748", "S758", "S759"
    }
    assert all(len(extraction) == 4 for extraction in entries.values())
    assert "LOSO" in entries["S083"]["leakage_control"]["value"]
    assert records["S083"]["validation"]["split_unit"] == "participant"
    assert records["S083"]["validation"]["external_validation"] == "no"
    assert entries["S084"]["split_unit"]["state"] == "not_reported"
    assert "full unlabeled real pool" in entries["S149"]["leakage_control"]["value"]
    assert "fourth external" in entries["S149"]["external_test"]["value"]
    assert "synthetic_only" not in records["S149"]["risk_flags"]
    assert records["S192"]["validation"]["split_unit"] == "participant"
    assert entries["S748"]["split_unit"]["state"] == "reported"
    assert "other 133 participants" in entries["S748"]["leakage_control"]["value"]
    assert "omits augmentation" in entries["S748"]["external_test"]["value"]
    assert entries["S758"]["split_unit"]["state"] == "not_reported"
    assert records["S758"]["validation"]["external_validation"] == "no"
    assert "labeled real training subjects" in entries["S759"]["leakage_control"]["value"]
    assert any("github.com/TaatiTeam/Pain-in-3D/blob/" in item["url"]
               for item in entries["S759"]["leakage_control"]["locators"])
    assert records["S759"]["validation"]["split_unit"] == "participant"


def test_ns06_prior_art_audit_keeps_mechanisms_and_search_limits_explicit() -> None:
    audit = load_json(DATA / "ns06-prior-art-audit.json")
    entries = {item["source_id"]: item for item in audit["analogue_decisions"]}

    assert audit["meta"]["status"] == "open"
    assert audit["s149_baseline"]["source_id"] == "S149"
    assert set(entries) == {
        "S035", "S083", "S084", "S088", "S192", "S748", "S758", "S759", "S791", "S792"
    }
    assert entries["S088"]["certainty"] == (
        "publisher_metadata_secondary_abstract_primary_methods_unavailable"
    )
    s088_access = entries["S088"]["primary_access_review"]
    assert s088_access["crossref"]["url"].endswith("11606012")
    assert "HTTP 418" in s088_access["publisher_pdf"]["result"]
    assert "full-text methods remain unavailable" in s088_access["decision"]
    assert "Full primary methods remain unavailable" in entries["S088"][
        "secondary_abstract_review"
    ]["decision"]
    assert entries["S791"]["related_version_ids"] == ["S792"]
    assert entries["S792"]["related_version_ids"] == ["S791"]
    assert entries["S791"]["locator"]["url"].endswith("1910.08173v1")
    assert any("2024" in item["section"] for item in entries["S791"]["locators"])
    assert "arousal and valence" in entries["S791"]["label_constructs"][
        "RECOLA_source"
    ]
    assert "six output groups" in entries["S792"]["label_constructs"][
        "UNBC_quantization_discrepancy"
    ]
    assert "labeled UNBC" in entries["S758"]["relation_to_s149"]
    assert "supervised real UNBC" in entries["S759"]["relation_to_s149"]
    assert audit["s759_author_code_check"]["state"] == "executable_protocol_resolved_reported_runs_unverified"
    assert audit["citation_search"]["s149_forward"]["indexed_cited_by_count"] == 0
    assert audit["citation_search"]["s149_forward"]["limit"]
    assert audit["s759_revision_check"]["state"] == "protocol_changed_between_versions"
    assert {item["variant_id"] for item in audit["variant_decisions"]} == {
        "NV-005", "NV-010", "NV-011"
    }


def test_scs_outcome_audit_separates_signals_and_clinical_endpoints() -> None:
    audit = load_json(DATA / "scs-outcome-audit.json")
    entries = {entry["source_id"]: entry["extraction"] for entry in audit["entries"]}
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}

    assert set(entries) == {
        "S003", "S033", "S034", "S046", "S105",
        "S159", "S236", "S239", "S360", "S749", "S779", "S780", "S781", "S788",
    }
    assert all(len(extraction) == 4 for extraction in entries.values())
    assert records["S003"]["evidence"]["target_construct"] == "self_reported_pain"
    assert entries["S003"]["prognostic_validation"]["state"] == "not_applicable"
    assert records["S033"]["evidence"]["sample_size"] == 17
    assert records["S033"]["evidence"]["modalities"] == ["eeg", "clinical_outcome"]
    assert "before LOOCV" in entries["S033"]["study_design"]["value"]
    assert records["S033"]["validation"]["external_validation"] == "no"
    assert entries["S105"]["prognostic_validation"]["state"] == "not_applicable"
    assert "therapy-experience" in entries["S239"]["target_role"]["value"]
    assert "AIVOC n=12" in entries["S749"]["prognostic_validation"]["value"]
    assert records["S749"]["validation"]["external_validation"] == "yes"
    assert entries["S779"]["prognostic_validation"]["state"] == "not_applicable"
    assert entries["S780"]["prognostic_validation"]["state"] == "not_applicable"
    assert entries["S781"]["prognostic_validation"]["state"] == "not_applicable"
    assert audit["study_families"][0]["source_ids"] == ["S779", "S780", "S781"]


def test_ns11_prediction_audit_retains_unresolved_primary_fields() -> None:
    audit = load_json(DATA / "ns11-prediction-audit.json")
    protocol = load_json(DATA / "search-protocol.json")
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-11")
    entries = {entry["source_id"]: entry["extraction"] for entry in audit["entries"]}

    assert set(entries) == set(stream["source_ids"])
    assert audit["meta"]["records_count"] == len(entries) == 14
    assert audit["meta"]["status"] == "in_progress"
    assert set(audit["meta"]["remaining_source_ids"]) == {"S034", "S046", "S755", "S762", "S804"}
    assert entries["S034"]["target"]["state"] == "not_reported"
    assert entries["S046"]["follow_up"]["state"] == "reported"
    assert entries["S046"]["patient_linkage"]["state"] == "not_reported"
    assert entries["S762"]["follow_up"]["state"] == "reported"
    assert entries["S762"]["target"]["state"] == "not_reported"
    assert entries["S804"]["target"]["state"] == "reported"
    assert entries["S804"]["follow_up"]["state"] == "reported"
    assert entries["S804"]["patient_linkage"]["state"] == "not_reported"
    assert audit["meta"]["unindexed_primary_leads"] == []
    lead = audit["meta"]["indexed_primary_leads"][0]
    assert lead["pmid"] == "32910099"
    assert lead["source_id"] == "S762"
    assert "thresholds" in lead["unresolved"]
    calodney = next(
        item for item in audit["meta"]["indexed_primary_leads"] if item["source_id"] == "S804"
    )
    assert calodney["status"].startswith("canonical_primary_abstract_card_published")
    assert "274/363" in calodney["version_discrepancy"]
    assert "267 responders and 96 nonresponders" in calodney["version_discrepancy"]
    assert records["S804"]["validation"]["status"] == "verified_primary"
    assert "subgroup count" in records["S804"]["evidence"]["target_label"].lower()
    assert "ecap" not in records["S804"]["evidence"]["modalities"]


def test_nociception_stream_and_larval_stage_use_primary_sources() -> None:
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}
    protocol = load_json(DATA / "search-protocol.json")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-03")

    assert len(stream["source_ids"]) >= 24
    assert set(stream["source_ids"]) <= set(records)
    assert stream["unindexed_primary_leads"] == []
    assert {lead["source_id"] for lead in stream["indexed_primary_leads"]} == {
        "S760", "S761", "S769", "S776", "S777", "S778", "S794", "S795", "S797", "S801", "S802", "S803"
    }
    for source_id in ("S030", "S092", "S154"):
        source = records[source_id]
        assert source["evidence"]["subject_domain"] == "drosophila_larva"
        assert source["evidence"]["species"] == "Drosophila melanogaster"
        resolution = source["field_resolution"]["evidence.subject_domain"]
        assert resolution["value"] == "drosophila_larva"
        assert resolution["locators"][0]["url"].startswith("https://")


def test_nociception_audit_separates_stimulus_neural_response_and_behavior() -> None:
    audit = load_json(DATA / "drosophila-nociception-audit.json")
    entries = {entry["source_id"]: entry["extraction"] for entry in audit["entries"]}
    records = {source["id"]: source for source in load_json(DATA / "records.json")["sources"]}

    assert audit["meta"]["status"] == "requires_primary_reconciliation"
    assert audit["meta"]["records_count"] == len(entries)
    assert len(entries) >= 24
    assert audit["meta"]["remaining_source_ids"] == []
    assert audit["meta"]["remaining_primary_access"] == []
    reconciliation = audit["meta"]["candidate_reconciliation"]
    assert reconciliation["status"] == "requires_primary_reconciliation"
    assert reconciliation["bounded_candidate_count"] == 27
    assert "not 27 verified" in reconciliation["count_basis"]
    assert audit["meta"]["unindexed_primary_leads"] == []
    assert set(entries) | set(audit["meta"]["remaining_source_ids"]) == set(
        audit["meta"]["candidate_source_ids"]
    )
    assert all(set(extraction) == {"stimulus", "neural_response", "behavior", "pain_boundary"} for extraction in entries.values())
    assert all(
        extraction["pain_boundary"]["reason"] and extraction["pain_boundary"]["locators"]
        for extraction in entries.values()
    )
    assert "subjective pain" in entries["S801"]["pain_boundary"]["value"]
    assert entries["S029"]["neural_response"]["state"] == "reported"
    assert entries["S012"]["stimulus"]["state"] == "not_applicable"
    assert entries["S013"]["neural_response"]["state"] == "reported"
    assert entries["S031"]["behavior"]["state"] == "reported"
    assert entries["S065"]["neural_response"]["state"] == "not_reported"
    assert entries["S090"]["neural_response"]["state"] == "not_reported"
    assert entries["S152"]["behavior"]["state"] == "not_applicable"
    assert entries["S154"]["behavior"]["state"] == "not_applicable"
    assert entries["S760"]["neural_response"]["state"] == "reported"
    assert entries["S761"]["behavior"]["state"] == "reported"
    assert entries["S776"]["neural_response"]["state"] == "reported"
    assert entries["S777"]["neural_response"]["state"] == "not_reported"
    assert entries["S778"]["neural_response"]["state"] == "reported"
    assert entries["S794"]["neural_response"]["state"] == "not_reported"
    assert entries["S795"]["neural_response"]["state"] == "not_reported"
    assert entries["S797"]["neural_response"]["state"] == "reported"
    assert "GCaMP6m" in entries["S803"]["neural_response"]["value"]
    assert "not electrophysiology" in entries["S803"]["neural_response"]["value"]
    assert records["S803"]["identifiers"]["doi"] == "10.1371/journal.pgen.1007464"
    assert records["S803"]["validation"]["status"] == "verified_primary"
    assert "119" in entries["S212"]["neural_response"]["value"]
    assert "rolling" in entries["S212"]["behavior"]["value"]
    assert records["S212"]["validation"]["full_text_status"] == "checked"
    assert records["S212"]["evidence"]["subject_domain"] == "drosophila_larva"
    assert records["S282"]["validation"]["status"] == "verified_primary"
    assert records["S282"]["validation"]["full_text_status"] == "checked"
    assert records["S282"]["evidence"]["subject_domain"] == "drosophila_larva"
    assert "27.5°C" in entries["S282"]["stimulus"]["value"]
    assert "N=8" in entries["S282"]["neural_response"]["value"]
    assert "behavioral group totals" in entries["S282"]["behavior"]["value"]
    assert "9F8BAAE" in next(item for item in audit["entries"] if item["source_id"] == "S282")["primary_fulltext_sha256"]
    assert audit["meta"]["unindexed_primary_leads"] == []
    assert {lead["source_id"] for lead in audit["meta"]["indexed_primary_leads"]} == {
            "S760", "S761", "S769", "S776", "S777", "S778", "S794", "S795", "S797", "S801", "S802", "S803"
    }
    assert records["S012"]["evidence"]["subject_domain"] == "mixed"
    assert records["S027"]["evidence"]["subject_domain"] == "mixed"
    assert records["S065"]["evidence"]["subject_domain"] == "drosophila_adult"
    assert records["S152"]["evidence"]["subject_domain"] == "drosophila_larva"
    assert records["S013"]["evidence"]["access_status"] == "open"
    assert records["S013"]["identifiers"]["exact_url"].startswith(
        "https://digital.lib.washington.edu/"
    )
