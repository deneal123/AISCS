"""Атомарные structural proposals: порядок, выделение, конфликт ID и отсутствие потери блоков."""

from copy import deepcopy

import pytest
from domain.documents.block_patch import BlockPatchError, apply_block_patch


def block(identity, text="Без изменений"):
    return {"block_id": identity, "kind": "slide", "text": text}


def patch(**changes):
    return {
        "patch_version": 2,
        "replacements": [],
        "deletions": [],
        "insertions": [],
        "moves": [],
        **changes,
    }


def test_three_cat_slides_preserve_other_content_and_inputs():
    original = [block("intro"), block("keep"), block("ending")]
    value = patch(
        replacements=[block("intro", "О котиках")],
        insertions=[
            {"after_id": "intro", "block": block("new_cat_2", "Повадки")},
            {"after_id": "new_cat_2", "block": block("new_cat_3", "Забота")},
        ],
    )
    saved = deepcopy((original, value))
    result = apply_block_patch(original, value, selected_ids=["intro"])
    assert [item["block_id"] for item in result] == [
        "intro",
        "new_cat_2",
        "new_cat_3",
        "keep",
        "ending",
    ]
    assert result[-2:] == original[-2:] and result[0]["text"] == "О котиках"
    assert (original, value) == saved


def test_canonical_delete_insert_move_is_atomic():
    original = [block("one"), block("two"), block("three")]
    value = patch(
        deletions=["two"],
        insertions=[{"after_id": "one", "block": block("new_four")}],
        moves=[{"block_id": "three", "after_id": ""}],
    )
    assert [item["block_id"] for item in apply_block_patch(original, value)] == [
        "three",
        "one",
        "new_four",
    ]


@pytest.mark.parametrize(
    "value,selected,code",
    [
        (patch(deletions=["one"]), ["two"], "outside_selection"),
        (
            patch(insertions=[{"after_id": "one", "block": block("new_four")}]),
            ["two"],
            "outside_selection",
        ),
        (
            patch(insertions=[{"after_id": "", "block": block("new_four")}]),
            ["two"],
            "outside_selection",
        ),
        (patch(moves=[{"block_id": "two", "after_id": "three"}]), ["two"], "outside_selection"),
        (patch(moves=[{"block_id": "two", "after_id": "missing"}]), None, "unknown_anchor"),
        (patch(moves=[{"block_id": "two", "after_id": "two"}]), None, "invalid_patch"),
        (patch(deletions=["one", "two", "three"]), None, "invalid_draft"),
        (patch(replacements=[block("absent")]), None, "unknown_block_id"),
        (
            patch(replacements=[{"block_id": "one", "kind": "paragraph"}]),
            None,
            "block_kind_changed",
        ),
        (patch(deletions=["one", "one"]), None, "duplicate_block_id"),
        (patch(replacements=[block("one")], deletions=["one"]), None, "duplicate_block_id"),
        (
            patch(insertions=[{"after_id": "one", "block": block("unassigned")}]),
            None,
            "new_block_id_required",
        ),
        (
            patch(
                insertions=[
                    {"after_id": "one", "block": block("new_four")},
                    {"after_id": "one", "block": block("new_four")},
                ]
            ),
            None,
            "duplicate_block_id",
        ),
        (
            patch(insertions=[{"after_id": "one", "block": block("new_four"), "extra": True}]),
            None,
            "invalid_patch",
        ),
        (patch(deletions=["two"]), "", "outside_selection"),
    ],
)
def test_invalid_batch_never_partially_changes_original(value, selected, code):
    original = [block("one"), block("two"), block("three")]
    saved = deepcopy((original, value))
    with pytest.raises(BlockPatchError, match=code) as raised:
        apply_block_patch(original, value, selected_ids=selected)
    assert raised.value.code == code and (original, value) == saved


def test_legacy_replacements_remain_readable_but_do_not_smuggle_structure():
    original = [block("one"), block("two")]
    assert (
        apply_block_patch(original, {"replacements": [block("two", "Правка")]})[1]["text"]
        == "Правка"
    )
    with pytest.raises(BlockPatchError, match="invalid_patch"):
        apply_block_patch(original, {"replacements": [block("two")], "deletions": ["one"]})


def test_block_and_operation_caps_are_not_increased():
    original = [block(f"block_{index}") for index in range(120)]
    with pytest.raises(BlockPatchError, match="invalid_draft"):
        apply_block_patch(
            original, patch(insertions=[{"after_id": "", "block": block("new_over")}])
        )
    with pytest.raises(BlockPatchError, match="invalid_patch"):
        apply_block_patch(original, patch(replacements=[block(f"block_{i}") for i in range(33)]))
