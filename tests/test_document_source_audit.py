"""Source audit must distinguish active authored input from comments and orphans."""

import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    spec = importlib.util.spec_from_file_location("document_source_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project(tmp_path: Path, source: str, *, references: bool = False) -> Path:
    (tmp_path / "document.toml").write_text(
        'entrypoint = "main.tex"\ndocumentclass = "article"\npaper = "a4"\n'
        'orientation = "portrait"\nrequired_sections = ["Mandatory"]\n'
        'source_export = "allowed"\n' + f"bibliography_required = {str(references).lower()}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    if references:
        (tmp_path / "bibliography").mkdir()
        (tmp_path / "bibliography/references.bib").write_text(
            "@misc{fixture,title={Synthetic fixture},year={2024}}", encoding="utf-8"
        )
    return tmp_path


def codes(path: Path) -> set[str]:
    diagnostics = runner().manifest_audit(
        path,
        {"page_count": 1, "page_width_pt": 595.3, "page_height_pt": 841.9},
        publication=True,
    )
    return {item["code"] for item in diagnostics}


@pytest.mark.parametrize("comment", ["% Mandatory", r"% \section{Mandatory}"])
def test_comment_cannot_satisfy_a_required_section(tmp_path: Path, comment: str) -> None:
    path = project(tmp_path, "\\documentclass{article}\n" + comment + "\nBody")
    assert "required_section" in codes(path)


def test_incidental_body_word_is_not_a_required_heading(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article} Body mentions Mandatory but has no heading.")
    assert "required_section" in codes(path)


def test_commented_placeholders_do_not_block_publication(tmp_path: Path) -> None:
    path = project(
        tmp_path,
        "\\documentclass{article}\n\\section{Mandatory}\n"
        "% \\DocumentPlaceholder{old} {{OLD_FIELD}}\nBody",
    )
    assert "unresolved_placeholder" not in codes(path)


def test_commented_citation_does_not_satisfy_evidence(tmp_path: Path) -> None:
    path = project(
        tmp_path,
        "\\documentclass{article}\n\\section{Mandatory}\n% \\cite{fixture}\nBody",
        references=True,
    )
    assert "citation_missing" in codes(path)


@pytest.mark.parametrize("recorder", [False, True])
def test_unused_file_does_not_supply_heading_or_citation(tmp_path: Path, recorder: bool) -> None:
    path = project(tmp_path, r"\documentclass{article} Body", references=True)
    (path / "unused.tex").write_text(r"\section{Mandatory}\cite{fixture}", encoding="utf-8")
    if recorder:
        (path / "main.fls").write_text("INPUT main.tex\n", encoding="utf-8")
    assert {"required_section", "citation_missing"} <= codes(path)


def test_unused_file_placeholder_does_not_poison_current_build(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\section{Mandatory} Body")
    (path / "unused.tex").write_text(r"\DocumentPlaceholder{old}", encoding="utf-8")
    assert "unresolved_placeholder" not in codes(path)


@pytest.mark.parametrize("recorder", [False, True])
def test_actual_nested_input_supplies_heading_and_citation(tmp_path: Path, recorder: bool) -> None:
    path = project(tmp_path, r"\documentclass{article}\input{content/body}", references=True)
    (path / "content").mkdir()
    (path / "content/body.tex").write_text(r"\section{Mandatory}\cite{fixture}", encoding="utf-8")
    if recorder:
        (path / "main.fls").write_text(
            "INPUT main.tex\nINPUT ./content/body.tex\n", encoding="utf-8"
        )
    assert not {"required_section", "citation_missing"} & codes(path)


def test_recorder_is_authoritative_for_computed_input_name(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\def\file{content/body}\input{\file}")
    (path / "content").mkdir()
    (path / "content/body.tex").write_text(r"\section{Mandatory}", encoding="utf-8")
    (path / "main.fls").write_text("INPUT main.tex\nINPUT ./content/body.tex\n", encoding="utf-8")
    assert "required_section" not in codes(path)


def test_commented_documentclass_is_not_the_actual_class(tmp_path: Path) -> None:
    path = project(
        tmp_path, "% \\documentclass{article}\n\\documentclass{report}\n\\section{Mandatory}"
    )
    assert "documentclass_mismatch" in codes(path)


def test_escaped_percent_does_not_hide_real_placeholder(tmp_path: Path) -> None:
    path = project(
        tmp_path, r"\documentclass{article}\section{Mandatory} 10\% \DocumentPlaceholder{actual}"
    )
    assert "unresolved_placeholder" in codes(path)


@pytest.mark.parametrize(
    "literal",
    [r"\verb|\section{Mandatory}|", "\\begin{verbatim}\n\\section{Mandatory}\n\\end{verbatim}"],
)
def test_literal_code_sample_cannot_supply_a_required_heading(tmp_path: Path, literal: str) -> None:
    path = project(tmp_path, "\\documentclass{article}\n" + literal)
    assert "required_section" in codes(path)


def test_comment_cannot_open_an_unused_input_in_fallback(tmp_path: Path) -> None:
    path = project(tmp_path, "\\documentclass{article}\n% \\input{unused}\nBody")
    (path / "unused.tex").write_text(r"\section{Mandatory}", encoding="utf-8")
    assert "required_section" in codes(path)


def test_input_cycles_are_read_once_without_global_directory_scan(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\input{body}")
    (path / "body.tex").write_text(r"\input{main}\section{Mandatory}", encoding="utf-8")
    source = runner().project_tex_source(path)
    assert source.count(r"\section{Mandatory}") == 1


def test_recorded_outside_and_hidden_inputs_do_not_leak_source(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\section{Mandatory}")
    external = tmp_path.parent / (tmp_path.name + "-outside.tex")
    external.write_text("PRIVATE_SOURCE_SENTINEL", encoding="utf-8")
    (path / ".private.tex").write_text("PRIVATE_SOURCE_SENTINEL", encoding="utf-8")
    (path / "main.fls").write_text(
        f"INPUT main.tex\nINPUT {external}\nINPUT .private.tex\n", encoding="utf-8"
    )
    try:
        assert "PRIVATE_SOURCE_SENTINEL" not in runner().project_tex_source(path)
    finally:
        external.unlink()


def test_missing_main_in_recorder_fails_closed(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\section{Mandatory}")
    (path / "main.fls").write_text("INPUT /etc/texmf/latex.tex\n", encoding="utf-8")
    assert "authoring_invalid" in codes(path)


def test_invalid_encoding_is_not_silently_erased(tmp_path: Path) -> None:
    path = project(tmp_path, r"\documentclass{article}\input{body}")
    (path / "body.tex").write_bytes(b"\xff\xfePRIVATE_SOURCE_SENTINEL")
    assert "authoring_invalid" in codes(path)


def test_byte_limit_fails_closed_without_partial_coverage(tmp_path: Path, monkeypatch) -> None:
    import document_source_audit

    path = project(tmp_path, r"\documentclass{article}\section{Mandatory}")
    monkeypatch.setattr(document_source_audit, "MAX_SOURCE_AUDIT_BYTES", 8)
    assert "authoring_invalid" in codes(path)


def test_file_limit_fails_closed_without_partial_coverage(tmp_path: Path, monkeypatch) -> None:
    import document_source_audit

    path = project(tmp_path, r"\documentclass{article}\input{body}")
    (path / "body.tex").write_text(r"\section{Mandatory}", encoding="utf-8")
    monkeypatch.setattr(document_source_audit, "MAX_SOURCE_AUDIT_FILES", 1)
    assert "authoring_invalid" in codes(path)
