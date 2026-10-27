"""Детерминированная проекция предложения для просмотра; никаких эффектов."""

from fastapi import HTTPException

from service.shared.block_patch import BlockPatchError, apply_block_patch


def proposal_draft(before: dict, proposal: dict, *, stale: bool) -> dict:
    if stale:
        # Нет сохранённой базовой структуры: нельзя выдавать сравнение с новой
        # версией за первоначальное предложение. Применение всё равно запрещено.
        return before
    try:
        blocks = apply_block_patch(
            before["blocks"], proposal, selected_ids=proposal.get("selected_block_ids")
        )
    except (BlockPatchError, KeyError, TypeError):
        raise HTTPException(status_code=422, detail="document_proposal_invalid") from None
    return {**before, "blocks": blocks}
