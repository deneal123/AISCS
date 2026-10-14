"""Compiler locations cannot cross the managed/vendor source boundary."""

import pytest
from application.documents.builds import DocumentBuildManager
from domain.documents.source_identity import source_path
from test_document_compiler_location import runner


def test_runner_retains_project_relative_source_identity():
    report = runner().diagnostics(
        "./content/body.tex:23: Missing $ inserted.", compilation_failed=True
    )
    assert report[0]["path"] == "body.tex"
    assert report[0]["source_path"] == "content/body.tex"


def test_vendor_basename_collision_never_targets_managed_block():
    report = {
        "diagnostics": runner().diagnostics(
            "vendor/body.tex:23: Missing $ inserted.", compilation_failed=True
        )
    }
    diagnostics = DocumentBuildManager._diagnostics(report, {"body.tex": "intro-001"})
    assert diagnostics[0].block_id == ""


def test_managed_location_uses_full_path_not_vendor_basename():
    report = {
        "diagnostics": runner().diagnostics(
            "content/body.tex:23: Missing $ inserted.", compilation_failed=True
        )
    }
    diagnostics = DocumentBuildManager._diagnostics(report, {"content/body.tex": "intro-001"})
    assert diagnostics[0].block_id == "intro-001"
    assert diagnostics[0].relative_path == "body.tex"


def test_legacy_basename_report_does_not_guess_source_ownership():
    report = {"diagnostics": [{"code": "compile_failed", "path": "body.tex", "line": 3}]}
    diagnostics = DocumentBuildManager._diagnostics(report, {"body.tex": "intro-001"})
    assert diagnostics[0].block_id == ""


def test_explicit_invalid_identity_does_not_fall_back_to_legacy_path():
    report = {
        "diagnostics": [
            {"code": "compile_failed", "path": "content/body.tex", "source_path": "", "line": 3}
        ]
    }
    diagnostics = DocumentBuildManager._diagnostics(report, {"content/body.tex": "intro-001"})
    assert diagnostics[0].block_id == ""


@pytest.mark.parametrize(
    "path",
    [
        "/job/content/body.tex",
        "../content/body.tex",
        "content/../body.tex",
        "content//body.tex",
        "content/./body.tex",
        "content\\body.tex",
        "content/\x00body.tex",
        "C:/content/body.tex",
        "././content/body.tex",
        "content/body.tex" + "x" * 201,
    ],
)
def test_unsafe_location_cannot_claim_a_source_identity(path):
    assert source_path(path) == ""


@pytest.mark.parametrize("path", ["/job/content/body.tex", "../content/body.tex"])
def test_runner_marks_unsafe_locations_unowned(path):
    diagnostics = runner().diagnostics(f"{path}:3: Missing $ inserted.", compilation_failed=True)
    assert diagnostics[0]["source_path"] == ""


def test_two_managed_directories_with_same_basename_remain_distinct():
    report = {
        "diagnostics": runner().diagnostics(
            "content/appendix/body.tex:3: Missing $ inserted.", compilation_failed=True
        )
    }
    provenance = {"content/body.tex": "intro-001", "content/appendix/body.tex": "appendix-001"}
    assert DocumentBuildManager._diagnostics(report, provenance)[0].block_id == "appendix-001"


def test_private_source_identity_does_not_expand_public_diagnostic_contract():
    report = {
        "diagnostics": runner().diagnostics(
            "content/body.tex:3: Missing $ inserted.", compilation_failed=True
        )
    }
    public = DocumentBuildManager._diagnostics(report, {"content/body.tex": "intro-001"})[0]
    assert public.public_dict() == {
        "severity": "error",
        "code": "missing_math_delimiter",
        "path": "body.tex",
        "line": 3,
        "count": 1,
        "block_id": "intro-001",
    }
