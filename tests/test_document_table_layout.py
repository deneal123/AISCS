"""Managed tables must retain rows and account for TeX column padding."""

from dataclasses import replace

import pytest

from service.domain.documents.intent import DocumentIntent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.documents.semantic.rendering import _table, render_document


def table(columns: int, rows: int = 90) -> DraftBlock:
    return DraftBlock(
        "coverage_table",
        "table",
        title="Coverage",
        columns=tuple(f"Column {index}" for index in range(columns)),
        rows=tuple(
            tuple(f"row{index:03d}" if column == 0 else "sample" for column in range(columns))
            for index in range(rows)
        ),
    )


@pytest.mark.parametrize("columns", [1, 2, 5, 6, 12, 24])
def test_long_table_is_breakable_and_deducts_intercolumn_padding(columns: int) -> None:
    rendered = _table(table(columns))
    assert "\\begin{longtable}" in rendered
    assert "\\begin{table}" not in rendered
    assert (
        rendered.count(
            f"p{{\\dimexpr(\\linewidth-{2 * (columns - 1)}\\tabcolsep)/{columns}\\relax}}"
        )
        == columns
    )
    assert "\\endfirsthead" in rendered and "\\endhead" in rendered
    for index in range(90):
        assert rendered.count(f"row{index:03d}") == 1


def test_short_table_and_compact_slide_do_not_gain_longtable() -> None:
    assert "\\begin{tabularx}" in _table(table(6, 12))
    assert "\\begin{longtable}" not in _table(table(6), compact=True)


@pytest.mark.parametrize(
    "preamble",
    [
        "\\documentclass[journal]{IEEEtran}",
        "\\documentclass[10pt,twocolumn,letterpaper]{article}",
        "\\documentclass{article}\n\\twocolumn",
    ],
)
def test_two_column_profile_cannot_silently_render_incompatible_longtable(preamble: str) -> None:
    intent = DocumentIntent(
        1,
        "table",
        "generic",
        "generic_document",
        "en-US",
        "draft",
        "Table",
        "reader",
        "long",
        (),
        "none",
        "balanced",
        (),
        (),
    )
    with pytest.raises(ValueError, match="^authoring_unsupported$"):
        render_document(
            replace(intent, title="Coverage"),
            DocumentDraft(1, 1, "Coverage", (table(6),)),
            scaffold_source=preamble + "\n\\begin{document}\nold\n\\end{document}",
        )
