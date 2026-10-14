"""Real natbib/biblatex syntax must not be rejected as missing evidence."""

import importlib.util
from pathlib import Path

import pytest


def runner():
    spec = importlib.util.spec_from_file_location(
        "citation_form_runner", Path(__file__).resolve().parents[1] / "docker/document_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "citation",
    [
        r"\citep{source}",
        r"\citet{source}",
        r"\parencite[see][p. 3]{source}",
        r"\cite [p. 3] {source}",
    ],
)
def test_valid_citation_dialect_satisfies_article_audit(tmp_path, citation):
    (tmp_path / "document.toml").write_text(
        'entrypoint="main.tex"\ndocumentclass="article"\npaper="a4"\n'
        'orientation="portrait"\nbibliography_required=true\n'
        'required_sections=[]\nsource_export="forbidden"\n',
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Evidence "
        + citation
        + r"\bibliography{bibliography/references}\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "bibliography").mkdir()
    (tmp_path / "bibliography/references.bib").write_text(
        "@misc{source,title={Synthetic source},year={2024}}",
        encoding="utf-8",
    )
    diagnostics = runner().manifest_audit(
        tmp_path,
        {"page_count": 1, "page_width_pt": 595.3, "page_height_pt": 841.9},
        publication=True,
    )
    assert "citation_missing" not in {item["code"] for item in diagnostics}


@pytest.mark.parametrize(
    "source",
    [
        r"\cite{}",
        r"\cite{ }",
        r"\cite{,}",
        r"\cite{source,}",
        r"\citation{source}",
        r"\citepAlias{source}",
        r"% \citep{source}",
        r"\verb|\citep{source}|",
    ],
)
def test_empty_unknown_or_inactive_citations_do_not_supply_evidence(source):
    compiler = runner()
    assert not compiler.has_citation(compiler.active_tex(source))
