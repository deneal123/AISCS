"""Сохранение и восстановление ACK private-предложения, без записи исходников."""

import json
import re

from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools.workspace.client import WorkspaceUnavailable
from service.shared.document_review import review_proposal_id

_ID = re.compile(r"[a-f0-9]{32}")
_DEFINITE_REFUSALS = {"invalid", "policy", "conflict", "expired"}


def restore_review_reference(execution, name: str, text: str) -> None:
    """Только результат доверенного адаптера/receipt, никогда текст модели."""
    if name not in {"tex_propose_patch", "tex_propose_structure"}:
        return
    try:
        result = json.loads(text)
    except (TypeError, ValueError):
        return
    if not isinstance(result, dict) or result.get("status") != "awaiting_review":
        return
    proposal_id = result.get("proposal_id")
    if isinstance(proposal_id, str) and _ID.fullmatch(proposal_id):
        execution.policy.set_value("document_proposal", proposal_id)


def _unconfirmed(execution) -> ToolCallOutcome:
    execution.workspace.document_unconfirmed = True
    return ToolCallOutcome(
        json.dumps(
            {
                "status": "unknown",
                "error_code": "operation_unknown",
                "message": (
                    "Подтверждение предложения недоступно. Исходники не применены. "
                    "Не повторяй запись: требуется сверить сохранённую операцию."
                ),
            },
            ensure_ascii=False,
        ),
        "failed",
        0,
        billable=False,
        failure_code=ToolFailureCode.UNAVAILABLE,
    )


async def _read_ack(reference, target, proposal, *, send) -> dict | None:
    proposal_id = review_proposal_id(target["path"], proposal)
    try:
        stored = await send(reference, "documents/proposals/read", {"proposal_id": proposal_id})
    except WorkspaceUnavailable:
        return None
    if not isinstance(stored, dict):
        return None
    if (
        stored.get("proposal_id") != proposal_id
        or stored.get("path") != target["path"]
        or stored.get("proposal") != proposal
    ):
        return None
    return {"proposal_id": proposal_id}


async def save_review_proposal(
    execution, reference, target, operations, *, send
) -> ToolCallOutcome:
    proposal = {
        **operations,
        "draft_digest": target["draft_digest"],
        "expected_revision": target["expected_revision"],
        "selected_block_ids": target.get("block_ids") or [],
    }
    try:
        result = await send(
            reference,
            "documents/proposals",
            {
                "path": target["path"],
                "expected_revision": target["expected_revision"],
                "proposal": proposal,
            },
        )
    except WorkspaceUnavailable as error:
        if error.reason_code in _DEFINITE_REFUSALS:
            from service.domain.tools.workspace.tools import _failure

            return _failure(error)
        result = await _read_ack(reference, target, proposal, send=send)
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("proposal_id"), str)
        or not _ID.fullmatch(result["proposal_id"])
    ):
        return _unconfirmed(execution)
    text = json.dumps({"status": "awaiting_review", "proposal_id": result["proposal_id"]})
    restore_review_reference(execution, "tex_propose_patch", text)
    return ToolCallOutcome(text, "succeeded", 0, reused=result.get("reused") is True)
