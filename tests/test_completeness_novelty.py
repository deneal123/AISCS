from pathlib import Path

from service.completeness import completeness_summary
from service.core import ResearchRepository, load_json
from service.integrity import validate_repository
from service.novelty import search_novelty

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_schema_2_has_no_unresolved_source_fields() -> None:
    records = load_json(DATA / "records.json")
    assert records["meta"]["schema_version"] == "2.0.0"
    summary = completeness_summary(records["sources"])
    assert summary["records"] == len(records["sources"])
    assert summary["unresolved_count"] == 0
    assert summary["resolved_fields"] == len(records["sources"]) * 36


def test_frontier_sources_and_two_model_boundaries_are_registered() -> None:
    repository = ResearchRepository(DATA)
    assert repository.get_source("S738")["identifiers"]["pmid"] == "42259917"
    assert repository.get_source("S739")["identifiers"]["doi"] == "10.64898/2026.08.21.745055"
    assert repository.get_source("S740")["identifiers"]["pmid"] == "42094485"
    concept = repository.dissertation_concept()
    forbidden = " ".join(concept["forbidden_claims"]).casefold()
    assert "direct digital twin" in forbidden
    assert "direct measure of pain" in forbidden


def test_ecap_patent_prior_art_narrows_but_does_not_close_novelty() -> None:
    repository = ResearchRepository(DATA)
    patent = repository.get_source("S746")
    assert patent["identifiers"]["patent_id"] == "WO2025224687A1"
    assert "patent_not_empirical_evidence" in patent["risk_flags"]
    assert patent["evidence"]["target_construct"] == "technical_signal_quality"
    landscape = load_json(DATA / "novelty-landscape.json")
    for variant in landscape["variants"]:
        assert "S746" in variant["closest_analogue_refs"]
        assert variant["prior_art_outcome"] == "partial_analogues_only"


def test_animal_closed_loop_analogue_preserves_construct_boundaries() -> None:
    source = ResearchRepository(DATA).get_source("S747")
    assert source["evidence"]["subject_domain"] == "animal_other"
    assert source["evidence"]["target_construct"] == "nociceptive_response"
    assert source["validation"]["split_unit"] == "recording"
    assert source["validation"]["cross_subject"] == "no"
    assert "ecap_not_pain_measure" in source["risk_flags"]


def test_human_generalization_review_preserves_target_boundaries() -> None:
    repository = ResearchRepository(DATA)
    s007 = repository.get_source("S007")
    s008 = repository.get_source("S008")
    s070 = repository.get_source("S070")
    s088 = repository.get_source("S088")

    assert s007["validation"]["split_unit"] == "participant"
    assert s007["validation"]["cross_subject"] == "yes"
    assert s007["evidence"]["target_construct"] == "experimental_pain_class"
    assert s008["validation"]["full_text_status"] == "checked"
    assert "entire cohort before folds" in s008["кросс_субъект"]
    assert "400" in s008["ограничения"]
    assert s070["validation"]["status"] == "verified_primary"
    assert s070["evidence"]["target_construct"] == "noxious_stimulus"
    assert s070["evidence"]["target_label"].startswith("Thermal painful versus")
    assert s088["validation"]["status"] == "verified_metadata"
    assert s088["validation"]["full_text_status"] == "unavailable"


def test_pain_baseline_review_keeps_constructs_separate() -> None:
    repository = ResearchRepository(DATA)
    review = repository.get_source("S005")
    fly = repository.get_source("S026")
    chronic = repository.get_source("S014")

    assert review["validation"]["split_unit"] == "study"
    assert fly["evidence"]["target_construct"] == "protective_behavior"
    assert fly["evidence"]["subject_domain"] == "drosophila_adult"
    assert chronic["evidence"]["target_construct"] == "clinical_function"
    assert chronic["validation"]["status"] == "partially_verified"


def test_pain_framework_rejects_interchangeable_measurements() -> None:
    source = ResearchRepository(DATA).get_source("S148")
    assert source["validation"]["status"] == "verified_primary"
    assert source["identifiers"]["pmid"] == "42454002"
    assert source["evidence"]["target_construct"] == "self_reported_pain"
    assert "non-interchangeable" in source["validation"]["notes"]


def test_patent_review_narrows_novelty_without_becoming_evidence() -> None:
    repository = ResearchRepository(DATA)
    optimization = repository.get_source("S098")
    sci_control = repository.get_source("S099")
    channel = repository.get_source("S241")
    unavailable = repository.get_source("S272")

    assert "patent_not_empirical_evidence" in optimization["risk_flags"]
    assert sci_control["evidence"]["target_construct"] == "clinical_function"
    assert "ecap_not_pain_measure" in sci_control["risk_flags"]
    assert channel["evidence"]["target_construct"] == "technical_signal_quality"
    assert channel["validation"]["calibration"] == "yes"
    assert unavailable["validation"]["full_text_status"] == "unavailable"


def test_remaining_metadata_review_has_terminal_boundaries_and_version_link() -> None:
    repository = ResearchRepository(DATA)
    thesis = repository.get_source("S071")
    unsupported = repository.get_source("S228")
    hardware = repository.get_source("S229")
    journal = repository.get_source("S748")

    assert thesis["validation"]["split_unit"] == "participant"
    assert thesis["evidence"]["sample_size"] == 36
    assert thesis["validation"]["external_validation"] == "no"
    assert unsupported["validation"]["status"] == "rejected"
    assert unsupported["validation"]["exclusion_reason"] == "irrelevant"
    assert hardware["evidence"]["target_construct"] == "technical_signal_quality"
    assert journal["identifiers"]["doi"] == "10.3390/computers15020127"
    assert journal["relations"][0]["target_id"] == "S035"
    assert journal["validation"]["cross_subject"] == "yes"
    assert journal["validation"]["split_unit"] == "participant"
    assert journal["validation"]["external_validation"] == "no"


def test_novelty_catalogue_is_unranked_and_searchable() -> None:
    result = search_novelty(DATA, query="closed-loop", limit=100)
    assert result["total"] >= 1
    landscape = load_json(DATA / "novelty-landscape.json")
    assert landscape["morphological_matrix"]["raw_combinations_count"] == 22500
    assert len(landscape["variants"]) == 15
    for item in landscape["variants"]:
        assert not ({"rank", "score", "confidence", "strength"} & set(item))
        assert "Drosophila" in item["bridge"]
        assert "ECAP" in item["bridge"]
        assert "SCS" in item["bridge"]


def test_current_repository_includes_novelty_integrity_gate() -> None:
    report = validate_repository(DATA)
    assert report["ok"], report["errors"]
    assert report["counts"]["novelty_variants"] == 15
    assert report["counts"]["unresolved_fields"] == 0
