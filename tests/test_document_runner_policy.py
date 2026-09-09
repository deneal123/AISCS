from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


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
