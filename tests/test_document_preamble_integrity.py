"""Semantic rendering must remove old titles and support admitted math commands."""

import pytest

from service.domain.documents.semantic.draft import DraftBlock
from service.domain.documents.semantic.rendering import _render_block, _trusted_preamble


@pytest.mark.parametrize(
    "old_title",
    [
        r"\title{\DocumentPlaceholder{Old title}}",
        r"\title{A \textbf{nested} title}",
        r"\title[Short]{A {nested} title}",
        "\\title {Multiline\n\\textbf{title}}",
        r"\title{Escaped \{ braces \} with {nested} group}",
    ],
)
def test_old_nested_title_does_not_survive_in_rendered_profile(old_title: str) -> None:
    preamble = _trusted_preamble(
        "\\documentclass{article}\n\\usepackage{fontspec}\n"
        + old_title
        + "\n\\author{Fixed Author}\n\\begin{document}old\\end{document}",
        "New & Title",
    )
    assert preamble.count("\\title") == 1
    assert "\\DocumentPlaceholder" not in preamble
    assert "\\title{New \\& Title}" in preamble
    assert "\\author{Fixed Author}" in preamble
    assert "\\usepackage{fontspec}" in preamble


def test_math_package_is_supplied_for_the_admitted_equation_subset() -> None:
    preamble = _trusted_preamble(
        "\\documentclass{article}\\begin{document}\\end{document}", "Title"
    )
    assert "\\usepackage{amsmath}" in preamble


def test_existing_math_package_is_not_loaded_again_or_loses_its_options() -> None:
    preamble = _trusted_preamble(
        "\\documentclass{article}\n\\usepackage[fleqn]{amsmath,amssymb}\n"
        "\\begin{document}\\end{document}",
        "Title",
    )
    assert "\\usepackage[fleqn]{amsmath,amssymb}" in preamble
    assert "\\usepackage{amsmath}" not in preamble


def test_unbalanced_trusted_title_is_rejected_instead_of_retained() -> None:
    with pytest.raises(ValueError, match="^invalid_scaffold$"):
        _trusted_preamble(
            "\\documentclass{article}\n\\title{Broken\n\\begin{document}\\end{document}",
            "New",
        )


def test_comments_and_escaped_percent_do_not_break_title_group_balancing() -> None:
    preamble = _trusted_preamble(
        "% License comment: \\title{not an active command\n"
        "\\documentclass{article}\n"
        "\\title{Progress 10\\% {nested} % commented closing }\nold}\n"
        "\\date{}\n\\begin{document}\\end{document}",
        "New",
    )
    assert "% License comment: \\title{not an active command" in preamble
    assert "Progress" not in preamble
    assert "\\date{}" in preamble
    assert "\\title{New}" in preamble


@pytest.mark.parametrize("text", ["A semantic paragraph.", "First part.\n\nSecond part."])
def test_semantic_paragraph_is_not_concatenated_with_adjacent_blocks(text: str) -> None:
    rendered = _render_block(
        DraftBlock("semantic_paragraph", "paragraph", text=text),
        report=False,
        article=False,
        citations=None,
        enforce_evidence=True,
    )
    assert rendered.startswith("\\par\n")
    assert rendered.endswith("\n\\par")
    assert text in rendered
