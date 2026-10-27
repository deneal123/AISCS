"""Версионированное структурное предложение, не запись источников или сборка."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from service.shared.block_patch import BlockPatchError, apply_block_patch

from .draft import DocumentDraft, parse_block, parse_document_draft
from .review import ReviewProblem


@dataclass(frozen=True, slots=True)
class StructureReview:
    base_version: int
    operations: dict[str, Any]
    draft: DocumentDraft


def _canonical_blocks(arguments: dict) -> dict:
    operations = deepcopy(arguments)
    for index, value in enumerate(operations["replacements"]):
        parsed = parse_block(value)
        if parsed is None:
            raise BlockPatchError("invalid_patch")
        operations["replacements"][index] = parsed.payload()
    for value in operations["insertions"]:
        parsed = parse_block(value.get("block")) if isinstance(value, dict) else None
        if parsed is None:
            raise BlockPatchError("invalid_patch")
        value["block"] = parsed.payload()
    return {**operations, "patch_version": 2}


def validate_structure_review(raw: str, target: dict) -> StructureReview | ReviewProblem:
    try:
        arguments = json.loads(raw)
    except (ValueError, TypeError):
        return ReviewProblem.INVALID_STRUCTURE
    keys = {"base_version", "replacements", "deletions", "insertions", "moves"}
    if (
        not isinstance(arguments, dict)
        or set(arguments) != keys
        or type(arguments.get("base_version")) is not int
        or any(not isinstance(arguments[name], list) for name in keys - {"base_version"})
    ):
        return ReviewProblem.INVALID_STRUCTURE
    if not 1 <= sum(len(arguments[name]) for name in keys - {"base_version"}) <= 32:
        return ReviewProblem.INVALID_STRUCTURE
    try:
        draft = parse_document_draft(json.loads(target.get("content") or "{}"))
    except (ValueError, TypeError):
        draft = None
    if draft is None:
        return ReviewProblem.DRAFT_UNAVAILABLE
    if arguments["base_version"] != draft.version:
        return ReviewProblem.STALE_VERSION
    try:
        operations = _canonical_blocks(arguments)
        blocks = apply_block_patch(
            draft.payload()["blocks"], operations, selected_ids=target.get("block_ids")
        )
    except BlockPatchError as error:
        return (
            ReviewProblem(error.code)
            if error.code != "invalid_patch"
            else ReviewProblem.INVALID_STRUCTURE
        )
    applied = parse_document_draft({**draft.payload(), "blocks": blocks})
    if applied is None:
        return ReviewProblem.INVALID_DRAFT
    return StructureReview(draft.version, operations, applied)
