"""Проверка предложения PDF-правок без записи, рендеринга или модельных эвристик."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .draft import (
    DocumentDraft,
    DraftPatch,
    apply_draft_patch,
    parse_document_draft,
    parse_draft_patch,
)


class ReviewProblem(StrEnum):
    INVALID_PATCH = "invalid_patch"
    DRAFT_UNAVAILABLE = "draft_unavailable"
    STALE_VERSION = "stale_base_version"
    UNKNOWN_BLOCK = "unknown_block_id"
    OUTSIDE_SELECTION = "outside_selection"
    INVALID_STRUCTURE = "invalid_structure"
    UNKNOWN_ANCHOR = "unknown_anchor"
    DUPLICATE_BLOCK = "duplicate_block_id"
    NEW_BLOCK_ID = "new_block_id_required"
    BLOCK_KIND_CHANGED = "block_kind_changed"
    INVALID_DRAFT = "invalid_draft"

    @property
    def message(self) -> str:
        return {
            self.INVALID_PATCH: (
                "Правка не прошла проверку: передай целую base_version и непустой список "
                "replacements с уникальными block_id и полями по схеме инструмента."
            ),
            self.DRAFT_UNAVAILABLE: (
                "Структура выбранного PDF-проекта недоступна. Не повторяй правку вслепую: "
                "нужно заново открыть актуальный документ."
            ),
            self.STALE_VERSION: (
                "base_version не совпадает с version переданной структуры документа. "
                "Не используй номер слайда как версию. Сверь текущую структуру; "
                "если она устарела, не повторяй правку вслепую."
            ),
            self.UNKNOWN_BLOCK: (
                "Указан отсутствующий block_id для замены, удаления или перемещения. "
                "Используй точные идентификаторы из blocks текущей структуры. "
                "Для вставки нужен tex_propose_structure, если этот инструмент доступен."
            ),
            self.OUTSIDE_SELECTION: (
                "Правка затрагивает блок вне выбранной области. Оставь только "
                "идентификаторы выделенных блоков; не изменяй остальные."
            ),
            self.INVALID_STRUCTURE: (
                "Передай base_version и четыре списка: replacements, deletions, insertions, moves. "
                "Пустые списки допустимы, но нужна хотя бы одна операция и не более 32 всего."
            ),
            self.UNKNOWN_ANCHOR: (
                "Якорь after_id отсутствует после удалений/предыдущих вставок. Укажи существующий "
                "ID либо пустую строку для начала документа; не используй удалённый блок."
            ),
            self.DUPLICATE_BLOCK: (
                "Идентификатор блока повторяется или заменяется и удаляется сразу."
            ),
            self.NEW_BLOCK_ID: (
                "Новый блок должен иметь уникальный временный ID с префиксом new_. "
                "Окончательный ID назначит доверенный renderer после применения."
            ),
            self.BLOCK_KIND_CHANGED: (
                "Тип существующего блока не меняется. Для другого типа предложи отдельные "
                "удаление старого и вставку нового блока, сохранив остальные."
            ),
            self.INVALID_DRAFT: "В документе должно остаться от 1 до 120 семантических блоков.",
        }[self]


@dataclass(frozen=True, slots=True)
class ReviewPatch:
    patch: DraftPatch
    draft: DocumentDraft

    @property
    def replacements(self) -> list[dict[str, Any]]:
        ids = {block.block_id for block in self.patch.replacements}
        return [block for block in self.draft.payload()["blocks"] if block["block_id"] in ids]


def validate_review_patch(raw: str, target: dict[str, Any]) -> ReviewPatch | ReviewProblem:
    try:
        arguments = json.loads(raw)
    except (ValueError, TypeError):
        return ReviewProblem.INVALID_PATCH
    if not isinstance(arguments, dict) or type(arguments.get("base_version")) is not int:
        return ReviewProblem.INVALID_PATCH
    patch = parse_draft_patch(arguments)
    if patch is None:
        return ReviewProblem.INVALID_PATCH
    try:
        draft = parse_document_draft(json.loads(target.get("content") or "{}"))
    except (ValueError, TypeError):
        draft = None
    if draft is None:
        return ReviewProblem.DRAFT_UNAVAILABLE
    if patch.base_version != draft.version:
        return ReviewProblem.STALE_VERSION
    ids = {block.block_id for block in patch.replacements}
    existing = {block.block_id: block for block in draft.blocks}
    if not ids <= existing.keys():
        return ReviewProblem.UNKNOWN_BLOCK
    if any(block.kind != existing[block.block_id].kind for block in patch.replacements):
        return ReviewProblem.BLOCK_KIND_CHANGED
    selected = set(target.get("block_ids") or [])
    if selected and not ids <= selected:
        return ReviewProblem.OUTSIDE_SELECTION
    applied = apply_draft_patch(draft, patch)
    return ReviewPatch(patch, applied) if applied is not None else ReviewProblem.INVALID_PATCH
