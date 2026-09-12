from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _runner() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "docker" / "document_runner.py"
    spec = importlib.util.spec_from_file_location("document_runtime_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _article(tmp_path: Path, *, source: str, bibliography: str) -> Path:
    project = tmp_path / "article"
    (project / "bibliography").mkdir(parents=True)
    (project / "document.toml").write_text(
        "\n".join(
            (
                'entrypoint = "main.tex"',
                'documentclass = "article"',
                'paper = "a4"',
                'orientation = "portrait"',
                "bibliography_required = true",
                'required_sections = ["Introduction", "References"]',
                'source_export = "allowed"',
                "anonymize = false",
            )
        ),
        encoding="utf-8",
    )
    (project / "main.tex").write_text(source, encoding="utf-8")
    (project / "bibliography" / "references.bib").write_text(bibliography, encoding="utf-8")
    return project


def test_draft_reports_missing_bibliography_without_blocking(tmp_path: Path) -> None:
    runner = _runner()
    project = _article(
        tmp_path,
        source=(
            "\\documentclass{article}\n"
            "\\begin{document}\\section{Introduction}Draft"
            "\\section{References}None\\end{document}"
        ),
        bibliography="% Verified records are added during authoring.\n",
    )

    diagnostics = runner.manifest_audit(
        project,
        {"page_count": 1, "page_width_pt": 595.28, "page_height_pt": 841.89},
        publication=False,
    )
    by_code = {item["code"]: item["severity"] for item in diagnostics}

    assert by_code["bibliography_missing"] == "warning"
    assert by_code["citation_missing"] == "warning"


def test_publication_requires_records_and_resolved_citation_intent(tmp_path: Path) -> None:
    runner = _runner()
    project = _article(
        tmp_path,
        source=(
            "\\documentclass{article}\n"
            "\\begin{document}\\section{Introduction}See \\cite{lamport1994}."
            "\\section{References}\\printbibliography\\end{document}"
        ),
        bibliography=(
            "@book{lamport1994, title={LaTeX: A Document Preparation System}, "
            "author={Lamport, Leslie}, year={1994}, publisher={Addison-Wesley}}\n"
        ),
    )

    diagnostics = runner.manifest_audit(
        project,
        {"page_count": 1, "page_width_pt": 595.28, "page_height_pt": 841.89},
        publication=True,
    )
    codes = {item["code"] for item in diagnostics}

    assert "bibliography_missing" not in codes
    assert "citation_missing" not in codes


def test_publication_rejects_legal_placeholders(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "legal"
    project.mkdir()
    (project / "document.toml").write_text(
        "\n".join(
            (
                'entrypoint = "main.tex"',
                'documentclass = "article"',
                'paper = "a4"',
                'orientation = "portrait"',
                "bibliography_required = false",
                'required_sections = ["Signatures"]',
                'source_export = "allowed"',
                "anonymize = false",
            )
        ),
        encoding="utf-8",
    )
    (project / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}"
        "\\section{Signatures}\\DocumentPlaceholder{Party name}"
        "\\end{document}",
        encoding="utf-8",
    )

    diagnostics = runner.manifest_audit(
        project,
        {"page_count": 1, "page_width_pt": 595.28, "page_height_pt": 841.89},
        publication=True,
    )

    assert any(
        item["code"] == "unresolved_placeholder" and item["severity"] == "error"
        for item in diagnostics
    )


def test_diagnostics_ignore_normal_tex_capability_probe() -> None:
    runner = _runner()

    diagnostics = runner.diagnostics(
        "Package pdftexcmds Info: \\pdfdraftmode not found.\n"
        "No file main.aux.\n"
        "Output written on main.pdf.\n"
    )

    assert "missing_file" not in {item["code"] for item in diagnostics}


def test_diagnostics_detect_actual_missing_tex_file() -> None:
    runner = _runner()

    diagnostics = runner.diagnostics(
        "! LaTeX Error: File `vendor-template.cls' not found.\n"
        "! I can't find file `content/chapter-one.tex'.\n"
    )

    missing = next(item for item in diagnostics if item["code"] == "missing_file")
    assert missing["severity"] == "error"
    assert missing["count"] == 2


def test_diagnostics_reject_missing_font_glyphs() -> None:
    runner = _runner()

    diagnostics = runner.diagnostics(
        "Missing character: There is no т (U+0442) in font LatinModernRoman!\n"
    )

    missing = next(item for item in diagnostics if item["code"] == "missing_glyph")
    assert missing["severity"] == "error"
    assert missing["count"] == 1


def test_effective_vendor_profile_is_applied_to_deterministic_audit(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "vendor"
    project.mkdir()
    (project / "document.toml").write_text(
        "\n".join(
            (
                "schema_version = 1",
                'profile_id = "generic_article"',
                "profile_version = 1",
                'entrypoint = "main.tex"',
                'documentclass = "article"',
                'paper = "a4"',
                'orientation = "portrait"',
                "max_pages = 8",
                'required_sections = ["Introduction"]',
                'source_export = "allowed"',
                "bibliography_required = false",
                "anonymize = false",
            )
        ),
        encoding="utf-8",
    )
    (project / "main.tex").write_text(
        "\\documentclass{vendorarticle}\\begin{document}"
        "\\section{Introduction}A\\section{Vendor Rules}B\\end{document}",
        encoding="utf-8",
    )
    (project / ".gpthub-effective-profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_profile_id": "generic_article",
                "base_profile_version": 1,
                "vendor_package_id": "journal-kit",
                "documentclass": "vendorarticle",
                "bibliography_style": "plain",
                "content_contract": "article",
                "paper": "a4",
                "orientation": "portrait",
                "max_pages": 4,
                "required_sections": ["Vendor Rules"],
                "export_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    diagnostics = runner.manifest_audit(
        project,
        {"page_count": 5, "page_width_pt": 595.28, "page_height_pt": 841.89},
        publication=False,
    )
    codes = {item["code"] for item in diagnostics}

    assert "vendor_profile_invalid" not in codes
    assert "documentclass_mismatch" not in codes
    assert "required_section" not in codes
    assert "page_limit" in codes


def test_effective_vendor_profile_must_match_the_exact_base_profile(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "vendor-invalid"
    project.mkdir()
    (project / "document.toml").write_text(
        "\n".join(
            (
                'profile_id = "generic_article"',
                "profile_version = 1",
                'entrypoint = "main.tex"',
                'documentclass = "article"',
                'paper = "a4"',
                'orientation = "portrait"',
                "max_pages = 8",
                "required_sections = []",
                "bibliography_required = false",
                "anonymize = false",
            )
        ),
        encoding="utf-8",
    )
    (project / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}ok\\end{document}", encoding="utf-8"
    )
    (project / ".gpthub-effective-profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_profile_id": "another_profile",
                "base_profile_version": 1,
                "vendor_package_id": "journal-kit",
                "documentclass": "vendorarticle",
                "bibliography_style": "plain",
                "content_contract": "article",
                "paper": "a4",
                "orientation": "portrait",
                "max_pages": 4,
                "required_sections": [],
                "export_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    diagnostics = runner.manifest_audit(
        project,
        {"page_count": 1, "page_width_pt": 595.28, "page_height_pt": 841.89},
        publication=False,
    )

    assert diagnostics == [{"severity": "error", "code": "vendor_profile_invalid", "count": 1}]


def test_renderer_block_labels_become_bounded_page_provenance(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "pages"
    project.mkdir()
    entrypoint = project / "main.tex"
    entrypoint.write_text("\\documentclass{article}", encoding="utf-8")
    (project / "main.aux").write_text(
        "\n".join(
            (
                r"\newlabel{gpthub:block:introduction}{{}{1}}",
                r"\newlabel{gpthub:block:results_table}{{}{3}}",
                r"\newlabel{not-managed}{{}{4}}",
            )
        ),
        encoding="utf-8",
    )

    assert runner.block_pages(project, entrypoint) == [
        {"block_id": "introduction", "page": 1},
        {"block_id": "results_table", "page": 3},
    ]


def test_authoring_manifest_requires_exact_digest_and_requested_sections(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "authoring"
    project.mkdir()
    draft = {
        "schema_version": 1,
        "version": 2,
        "title": "Report",
        "blocks": [
            {
                "block_id": "overview_section",
                "kind": "section",
                "title": "Overview",
                "text": "Body",
            }
        ],
    }
    digest = hashlib.sha256(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "draft_version": 2,
        "draft_digest": digest,
        "profile_id": "generic_report",
        "intent": {"required_sections": ["Overview", "Conclusion"]},
        "draft": draft,
    }
    path = project / ".gpthub-authoring.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    diagnostics = runner.authoring_manifest_audit(project, "generic_report")
    assert diagnostics == [{"severity": "error", "code": "required_section", "count": 1}]

    manifest["draft_digest"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert runner.authoring_manifest_audit(project, "generic_report") == [
        {"severity": "error", "code": "authoring_invalid", "count": 1}
    ]


def test_compiler_process_searches_only_the_project_local_vendor_tree(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _runner()
    captured = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stdout=b"", returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner.run(["latexmk"], tmp_path, 10.0)

    vendor = str((tmp_path / "vendor").resolve()) + "//:"
    assert captured["env"]["TEXINPUTS"].startswith(vendor)
    assert captured["env"]["BIBINPUTS"].startswith(vendor)
    assert captured["env"]["BSTINPUTS"].startswith(vendor)


def test_source_bundle_never_redistributes_project_local_vendor_files(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "project"
    (project / "vendor" / "journal-kit").mkdir(parents=True)
    (project / "content").mkdir()
    (project / "main.tex").write_text("safe", encoding="utf-8")
    (project / "content" / "body.tex").write_text("body", encoding="utf-8")
    (project / "vendor" / "journal-kit" / "private.cls").write_text("vendor", encoding="utf-8")
    (project / "main.xdv").write_bytes(b"compiler intermediate")
    (project / "main.aux").write_text("compiler state", encoding="utf-8")
    (project / "main.pdf").write_bytes(b"final artifact")
    target = tmp_path / "source.zip"

    runner.source_bundle(project, target)

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    assert "main.tex" in names
    assert "content/body.tex" in names
    assert not any(name.startswith("vendor/") for name in names)
    assert "main.xdv" not in names
    assert "main.aux" not in names
    assert "main.pdf" not in names


def test_source_bundle_is_an_allowlist_and_excludes_symlinks(tmp_path: Path) -> None:
    runner = _runner()
    project = tmp_path / "project"
    project.mkdir()
    (project / "document.toml").write_text("schema_version = 1", encoding="utf-8")
    (project / "diagram.svg").write_text("<svg/>", encoding="utf-8")
    (project / "engine.cache").write_bytes(b"not authored source")
    external = tmp_path / "outside.tex"
    external.write_text("private", encoding="utf-8")
    linked = project / "linked.tex"
    try:
        linked.symlink_to(external)
    except OSError:
        linked = None
    target = tmp_path / "source.zip"

    runner.source_bundle(project, target)

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    assert names >= {"document.toml", "diagram.svg"}
    assert "engine.cache" not in names
    if linked is not None:
        assert "linked.tex" not in names
