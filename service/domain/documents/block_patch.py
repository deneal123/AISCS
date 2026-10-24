"""Атомарная перестройка семантических блоков, без записи и подтверждения результата.

Одинаковая stdlib-копия в agents/backend/workspace проверяется shared-copy gate.
Порядок v2 фиксирован: замены, удаления, вставки, перемещения. Пустой after_id
означает начало документа, а не произвольный или отсутствующий якорь.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_GROUPS = ("replacements", "deletions", "insertions", "moves")


class BlockPatchError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise BlockPatchError("invalid_patch")
    return value


def _block(value: Any) -> dict:
    if not isinstance(value, dict):
        raise BlockPatchError("invalid_patch")
    _identity(value.get("block_id"))
    return deepcopy(value)


def _position(blocks: list[dict], block_id: str) -> int:
    for index, block in enumerate(blocks):
        if block["block_id"] == block_id:
            return index
    raise BlockPatchError("unknown_block_id")


def _anchor(blocks: list[dict], after_id: Any) -> int:
    if after_id == "":
        return 0
    try:
        return _position(blocks, _identity(after_id)) + 1
    except BlockPatchError:
        raise BlockPatchError("unknown_anchor") from None


def _editable(block_id: str, selected: set[str] | None) -> None:
    if selected is not None and block_id not in selected:
        raise BlockPatchError("outside_selection")


def _anchor_scope(after_id: Any, selected: set[str] | None, at_start: bool) -> None:
    if selected is None:
        return
    if after_id == "":
        if not at_start:
            raise BlockPatchError("outside_selection")
    else:
        _editable(_identity(after_id), selected)


def _groups(patch: dict, version: int) -> dict[str, list]:
    names = _GROUPS if version == 2 else ("replacements",)
    result = {}
    for name in names:
        values = patch.get(name)
        if not isinstance(values, list):
            raise BlockPatchError("invalid_patch")
        result[name] = values
    if not 1 <= sum(map(len, result.values())) <= 32:
        raise BlockPatchError("invalid_patch")
    return result


def _replace_delete(blocks: list[dict], groups: dict, selected: set[str] | None) -> None:
    replaced = set()
    for raw in groups["replacements"]:
        block = _block(raw)
        block_id = block["block_id"]
        if block_id in replaced:
            raise BlockPatchError("duplicate_block_id")
        replaced.add(block_id)
        _editable(block_id, selected)
        index = _position(blocks, block_id)
        if block.get("kind") != blocks[index].get("kind"):
            raise BlockPatchError("block_kind_changed")
        blocks[index] = block
    deleted = set()
    for raw in groups.get("deletions", []):
        block_id = _identity(raw)
        if block_id in deleted or block_id in replaced:
            raise BlockPatchError("duplicate_block_id")
        deleted.add(block_id)
        _editable(block_id, selected)
        blocks.pop(_position(blocks, block_id))


def _insert(
    blocks: list[dict],
    operations: list,
    original: set[str],
    selected: set[str] | None,
    at_start: bool,
) -> None:
    used = set(original)
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"after_id", "block"}:
            raise BlockPatchError("invalid_patch")
        block = _block(operation["block"])
        block_id = block["block_id"]
        if not block_id.startswith("new_"):
            raise BlockPatchError("new_block_id_required")
        if block_id in used:
            raise BlockPatchError("duplicate_block_id")
        used.add(block_id)
        _anchor_scope(operation["after_id"], selected, at_start)
        blocks.insert(_anchor(blocks, operation["after_id"]), block)
        if selected is not None:
            selected.add(block_id)


def _move(
    blocks: list[dict],
    operations: list,
    selected: set[str] | None,
    at_start: bool,
) -> None:
    moved = set()
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"block_id", "after_id"}:
            raise BlockPatchError("invalid_patch")
        block_id, after_id = _identity(operation["block_id"]), operation["after_id"]
        if block_id in moved or block_id == after_id:
            raise BlockPatchError("invalid_patch")
        moved.add(block_id)
        _editable(block_id, selected)
        _anchor_scope(after_id, selected, at_start)
        block = blocks.pop(_position(blocks, block_id))
        blocks.insert(_anchor(blocks, after_id), block)


def apply_block_patch(
    original: list[dict],
    patch: dict,
    *,
    selected_ids: list[str] | None = None,
) -> list[dict]:
    """Все проверки проходят на копии; ошибка никогда не меняет original или patch."""
    if not isinstance(original, list) or not 1 <= len(original) <= 120:
        raise BlockPatchError("invalid_draft")
    blocks = [_block(block) for block in original]
    known = {block["block_id"] for block in blocks}
    if len(known) != len(blocks):
        raise BlockPatchError("invalid_draft")
    if not isinstance(patch, dict):
        raise BlockPatchError("invalid_patch")
    version = patch.get("patch_version", 1)
    if type(version) is not int or version not in {1, 2}:
        raise BlockPatchError("invalid_patch")
    if version == 1 and any(name in patch for name in _GROUPS[1:]):
        raise BlockPatchError("invalid_patch")
    selected = None
    if selected_ids is not None and not isinstance(selected_ids, list):
        raise BlockPatchError("outside_selection")
    if selected_ids:
        if not isinstance(selected_ids, list):
            raise BlockPatchError("outside_selection")
        selected = {_identity(value) for value in selected_ids}
        if not selected <= known:
            raise BlockPatchError("outside_selection")
    at_start = selected is None or blocks[0]["block_id"] in selected
    groups = _groups(patch, version)
    _replace_delete(blocks, groups, selected)
    _insert(blocks, groups.get("insertions", []), known, selected, at_start)
    _move(blocks, groups.get("moves", []), selected, at_start)
    if not 1 <= len(blocks) <= 120:
        raise BlockPatchError("invalid_draft")
    return blocks
