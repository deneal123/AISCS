"""Проверка происхождения улучшения и принятие только после подтверждённой задачи."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.persistence.harness.state import save_checkpoint
from service.shared.harness_protocol import HarnessFailure
from service.shared.harness_refinement import proposal_from_message, render_refinement


def _confirmed_model_grant(grant):
    if not grant or grant.get("state") != "succeeded":
        return False
    request, receipt = grant.get("request"), grant.get("receipt")
    return bool(
        isinstance(request, dict)
        and not request.get("billing_tool")
        and isinstance(receipt, dict)
        and receipt.get("finish_reason") in ("stop", "tool_calls", "function_call")
        and not receipt.get("estimated")
        and isinstance(receipt.get("message"), dict)
    )


def _has_guidance(messages, proposal):
    expected = render_refinement(proposal)
    return isinstance(messages, list) and any(
        isinstance(message, dict)
        and message.get("role") == "user"
        and message.get("content") == expected
        for message in messages
    )


async def _grant(db, row, operation_id):
    grant = (
        (
            await db.execute(
                text(
                    "SELECT request,state,receipt FROM profile.harness_grant "
                    "WHERE task_id=:task AND operation_id=:operation"
                ),
                {"task": row["task_id"], "operation": UUID(operation_id)},
            )
        )
        .mappings()
        .first()
    )
    if not _confirmed_model_grant(grant):
        raise HarnessFailure("verification_missing")
    return grant


async def require_refinement_transition(db, row, current, new):
    old = current.continuation
    if old.refinement == new.refinement:
        return
    candidate = new.refinement
    if old.refinement is not None or candidate is None or candidate.adopted:
        raise HarnessFailure("operation_conflict")
    if (
        current.state is None
        or candidate.baseline_evidence_count != len(current.state.evidence)
        or candidate.probe_step != new.next_step
        or candidate.probe_step <= old.next_step
    ):
        raise HarnessFailure("operation_conflict")
    if not _has_guidance(new.conversation(), candidate.proposal):
        raise HarnessFailure("verification_missing")
    baseline = await _grant(db, row, candidate.baseline_operation)
    proposal = await _grant(db, row, candidate.proposal_operation)
    binding = old.provider
    if binding is None or any(
        (grant["request"].get("provider"), grant["request"].get("model"))
        != (binding.provider, binding.model)
        for grant in (baseline, proposal)
    ):
        raise HarnessFailure("provider_state_incompatible")
    if (
        baseline["request"].get("kind", "chat") != "chat"
        or baseline["request"].get("continuation_step") is None
        or baseline["request"]["continuation_step"] > old.next_step
        or proposal["request"].get("kind") != "meta_usage"
        or baseline["receipt"].get("finish_reason") != "stop"
        or baseline["receipt"]["message"].get("tool_calls")
    ):
        raise HarnessFailure("verification_missing")
    try:
        body = json.loads(baseline["request"]["canonical_request"])
        names = {tool["function"]["name"] for tool in body.get("tools") or []}
        proposed = proposal_from_message(proposal["receipt"]["message"])
        if proposed != candidate.proposal or any(tool.name not in names for tool in proposed.tools):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HarnessFailure("verification_missing") from None


async def _verified_probe(db, row, current, candidate):
    probes = (
        (
            await db.execute(
                text(
                    "SELECT request,state,receipt FROM profile.harness_grant WHERE task_id=:task "
                    "AND request->>'kind'='chat' AND request->>'continuation_step'=:step LIMIT 2"
                ),
                {"task": row["task_id"], "step": str(candidate.probe_step)},
            )
        )
        .mappings()
        .all()
    )
    if len(probes) != 1 or not _confirmed_model_grant(probes[0]):
        return False
    grant, binding = probes[0], current.continuation.provider
    calls = grant["receipt"]["message"].get("tool_calls")
    if (
        binding is None
        or (grant["request"].get("provider"), grant["request"].get("model"))
        != (binding.provider, binding.model)
        or not isinstance(calls, list)
        or not calls
        or grant["receipt"]["finish_reason"] not in ("tool_calls", "function_call")
    ):
        return False
    try:
        body = json.loads(grant["request"]["canonical_request"])
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(body, dict) and _has_guidance(body.get("messages"), candidate.proposal)


async def adopt_verified_refinement(db, row, current, result):
    if not result or result["status"] != "completed" or result.get("verified") is not True:
        return
    candidate = current.continuation.refinement
    if not candidate or candidate.adopted:
        return
    if len(current.state.evidence) <= candidate.baseline_evidence_count:
        return
    if not await _verified_probe(db, row, current, candidate):
        return
    # Модель не присылает adopted: он получается только из backend CompletionVerifier
    # после сверки unresolved операций, Stop и доверенных executor receipts.
    continuation = current.continuation.model_copy(
        update={"refinement": candidate.model_copy(update={"adopted": True})}
    )
    await save_checkpoint(db, row, state=current.state, continuation=continuation)
