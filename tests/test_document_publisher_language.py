import json

import pytest

from service.domain.documents.intent import parse_document_intent
from service.domain.documents.publisher_language import publisher_language
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock, parse_document_draft
from service.domain.documents.semantic.editor import render_edit
from service.domain.documents.semantic.rendering import render_document

SOURCE = (
    "\\documentclass[journal]{IEEEtran}\n"
    "\\usepackage[T1]{fontenc}\n\\usepackage[utf8]{inputenc}\n"
    "\\author{Fixed Author}\n\\begin{document}\nOriginal body\n\\end{document}\n"
)


@pytest.mark.parametrize("profile_id", ["ieee_journal", "aaai_conference"])
def test_russian_support_is_idempotent_and_preserves_publisher_policy(profile_id):
    result = publisher_language(SOURCE, profile_id=profile_id, locale="ru-RU")
    assert r"\usepackage[T2A,T1]{fontenc}" in result
    assert r"\usepackage[english,russian]{babel}" in result
    assert r"\documentclass[journal]{IEEEtran}" in result
    assert result.partition(r"\begin{document}")[2] == SOURCE.partition(r"\begin{document}")[2]
    assert publisher_language(result, profile_id=profile_id, locale="ru-RU") == result


@pytest.mark.parametrize(
    "profile,locale,source",
    [
        ("ieee_journal", "en-US", SOURCE),
        ("vendor_profile", "ru-RU", SOURCE),
        ("generic_document", "ru-RU", SOURCE),
        (
            "ieee_journal",
            "ru-RU",
            SOURCE.replace(r"\usepackage[T1]{fontenc}", r"\usepackage{fontspec}"),
        ),
        (
            "ieee_journal",
            "ru-RU",
            SOURCE.replace(r"\usepackage[T1]{fontenc}", r"% \usepackage[T1]{fontenc}"),
        ),
    ],
)
def test_other_languages_engines_vendor_templates_and_comments_are_untouched(
    profile, locale, source
):
    assert publisher_language(source, profile_id=profile, locale=locale) == source


def test_explicit_semantic_edit_upgrades_legacy_preamble_without_hiding_other_changes():
    intent = parse_document_intent(
        {
            "kind": "article",
            "profile_id": "ieee_journal",
            "locale": "ru-RU",
            "mode": "draft",
            "citation_policy": "none",
        },
        "",
    )
    draft = DocumentDraft(1, 1, "Черновик", (DraftBlock("intro", "paragraph", text="Текст"),))
    files = render_document(intent, draft, scaffold_source=SOURCE, enforce_evidence=False).files
    draft = parse_document_draft(json.loads(files[".gpthub-authoring.json"])["draft"])
    legacy = dict(files)
    legacy["main.tex"] = (
        legacy["main.tex"]
        .replace("[T2A,T1]", "[T1]")
        .replace("\\usepackage[english,russian]{babel}\n", "")
    )
    proposed = draft.payload()
    proposed["blocks"][0]["text"] = "Новая редакция"
    result = render_edit(legacy, proposed, draft.version, draft.digest)
    assert r"\usepackage[T2A,T1]{fontenc}" in result["files"]["main.tex"]
    assert r"\author{Fixed Author}" in result["files"]["main.tex"]
    legacy["main.tex"] = legacy["main.tex"].replace("Original body", "changed") + "% manual edit\n"
    with pytest.raises(ValueError, match="source_changed"):
        render_edit(legacy, proposed, draft.version, draft.digest)


def test_publisher_language_is_part_of_loaded_document_runtime_identity():
    from service.domain.documents.runtime_digest import _RUNTIME_FILES

    assert "publisher_language.py" in _RUNTIME_FILES
