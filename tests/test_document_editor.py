import json
from copy import deepcopy

import pytest

from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock, parse_block
from service.domain.documents.semantic.editor import render_edit, render_initial
from service.domain.documents.semantic.rendering import render_document


@pytest.fixture
def authored():
    intent = deterministic_intent("Подготовь документ")
    draft = DocumentDraft(
        1,
        1,
        "Обзор",
        (
            DraftBlock("intro", "paragraph", text="Исходный текст."),
            DraftBlock("closing", "paragraph", text="Неизменяемый раздел."),
        ),
    )
    rendered = render_document(
        intent,
        draft,
        scaffold_source="\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
    )
    return draft, rendered.files


def test_semantic_edit_is_deterministic_and_keeps_unaffected_block(authored):
    draft, files = authored
    changed = deepcopy(draft.payload())
    changed["blocks"][0]["text"] = "Новая редакция с кириллицей и 100% точностью."
    result = render_edit(files, changed, draft.version, draft.digest)
    assert result == render_edit(files, changed, draft.version, draft.digest)
    assert result["authoring_version"] == 2
    assert result["files"]["content/002-closing.tex"] == files["content/002-closing.tex"]
    assert r"100\%" in result["files"]["content/001-intro.tex"]


def test_first_pdf_project_initial_content_is_immediately_editable_without_a_model():
    files = {
        "main.tex": "\\documentclass[11pt,a4paper]{article}\n"
        "\\begin{document}\nНовый документ\n\\end{document}\n"
    }
    proposed = {"title": "Новый документ", "text": "Начните редактирование документа здесь."}
    project = {
        "kind": "generic",
        "profile": {"profile_id": "generic_document"},
        "locale": "ru-RU",
        "mode": "draft",
    }
    first = render_initial(files, proposed, project)
    assert first == render_initial(files, proposed, project)
    assert first["authoring_version"] == 1
    draft = json.loads(first["files"][".gpthub-authoring.json"])["draft"]
    assert draft["title"] == proposed["title"]
    assert draft["blocks"][0]["text"] == proposed["text"]
    edited = render_edit(first["files"], draft, 1, first["draft_digest"])
    assert edited["authoring_version"] == 2
    assert edited["files"]["main.tex"].startswith(r"\documentclass[11pt,a4paper]{article}")


@pytest.mark.parametrize("change", ["version", "digest", "manual", "unknown_block", "citation"])
def test_semantic_edit_rejects_unsafe_or_stale_input(authored, change):
    draft, files = authored
    files = dict(files)
    changed = draft.payload()
    digest = draft.digest
    version = draft.version
    if change == "version":
        version += 1
    elif change == "digest":
        digest = "0" * 64
    elif change == "manual":
        files["content/001-intro.tex"] += "Ручная правка.\n"
    elif change == "unknown_block":
        changed["blocks"][0]["block_id"] = "invented"
    else:
        changed["blocks"][0]["source_id"] = 45
    with pytest.raises(ValueError):
        render_edit(files, changed, version, digest)


def test_manual_table_keeps_empty_cell_positions(authored):
    draft, files = authored
    changed = draft.payload()
    changed["blocks"].append(
        {
            "block_id": "new_table",
            "kind": "table",
            "title": "Результаты",
            "columns": ["Метод", "Значение"],
            "rows": [["", "2"], ["", ""]],
        }
    )
    parsed = parse_block(changed["blocks"][-1])
    assert parsed is not None
    assert parsed.rows == (("", "2"), ("", ""))
    result = render_edit(files, changed, draft.version, draft.digest)
    tables = [text for text in result["files"].values() if r"\begin{tabularx}" in text]
    assert len(tables) == 1
    assert " & 2" in tables[0]
    assert result["files"]["content/002-closing.tex"] == files["content/002-closing.tex"]


def test_registered_citation_insertion_keeps_the_exact_bibliography(authored):
    from service.domain.documents.semantic.editor import ExistingCitations

    draft, _ = authored
    bib = "@misc{src1_aaaaaaaaaa, title={Real source}, url={https://example.test/a}}\n"
    files = render_document(
        deterministic_intent("Подготовь документ"),
        draft,
        scaffold_source="\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
        citations=ExistingCitations(bib),
        bibliography=bib,
    ).files
    changed = draft.payload()
    changed["blocks"].append(
        {"block_id": "new_citation", "kind": "citation", "text": "По данным", "source_id": 1}
    )
    result = render_edit(files, changed, draft.version, draft.digest)
    assert result["files"]["bibliography/references.bib"] == bib
    assert any(r"\cite{src1_aaaaaaaaaa}" in text for text in result["files"].values())
    changed["blocks"][-1]["source_id"] = 2
    with pytest.raises(ValueError, match="citation_unknown"):
        render_edit(files, changed, draft.version, draft.digest)
