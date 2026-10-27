"""Одна v2-правка проходит настоящий renderer, не подменяя authoring evidence."""

import json
from copy import deepcopy

import pytest

from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.documents.semantic.editor import render_edit
from service.domain.documents.semantic.rendering import render_document
from service.domain.documents.semantic.structure import StructureReview, validate_structure_review


def authored():
    draft = DocumentDraft(
        1,
        1,
        "Котики",
        (
            DraftBlock("intro", "paragraph", text="Первый фрагмент"),
            DraftBlock("keep", "paragraph", text="Сохранить этот текст"),
            DraftBlock("ending", "paragraph", text="Удаляемый фрагмент"),
        ),
    )
    files = render_document(
        deterministic_intent("Подготовь документ"),
        draft,
        scaffold_source="\\documentclass{article}\n\\begin{document}\n\\end{document}\n",
    ).files
    return draft, files


def proposal(draft):
    value = {
        "base_version": 1,
        "replacements": [
            DraftBlock("intro", "paragraph", text="Новое начало о котиках").payload(),
        ],
        "deletions": ["ending"],
        "insertions": [
            {
                "after_id": "intro",
                "block": DraftBlock("new_care", "paragraph", text="Забота").payload(),
            }
        ],
        "moves": [{"block_id": "keep", "after_id": ""}],
    }
    checked = validate_structure_review(json.dumps(value), {"content": json.dumps(draft.payload())})
    assert isinstance(checked, StructureReview)
    return checked


def test_replace_delete_insert_move_preserve_unaffected_bytes_and_assign_new_ids():
    draft, files = authored()
    saved = deepcopy(files)
    checked = proposal(draft)
    result = render_edit(files, checked.draft.payload(), draft.version, draft.digest)
    assert result == render_edit(files, checked.draft.payload(), draft.version, draft.digest)
    manifest = json.loads(result["files"][".gpthub-authoring.json"])
    blocks = manifest["draft"]["blocks"]
    assert result["authoring_version"] == 2
    assert [block["block_id"] for block in blocks[:2]] == ["keep", "intro"]
    assert blocks[2]["block_id"].startswith("block_") and blocks[2]["text"] == "Забота"
    assert result["files"]["content/001-keep.tex"] == files["content/002-keep.tex"]
    assert not any("ending" in path for path in result["files"])
    assert files == saved


def test_parallel_manual_source_edit_cannot_be_overwritten_by_structural_proposal():
    draft, files = authored()
    checked = proposal(draft)
    files["content/002-keep.tex"] += "Ручная правка пользователя\n"
    saved = deepcopy(files)
    with pytest.raises(ValueError, match="source_changed"):
        render_edit(files, checked.draft.payload(), draft.version, draft.digest)
    assert files == saved


def test_published_new_version_rejects_repeating_the_old_apply():
    draft, files = authored()
    checked = proposal(draft)
    result = render_edit(files, checked.draft.payload(), draft.version, draft.digest)
    with pytest.raises(ValueError, match="source_changed"):
        render_edit(result["files"], checked.draft.payload(), draft.version, draft.digest)
