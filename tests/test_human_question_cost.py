"""A decision belongs to the exact answered frame, not a general paid-run flag."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.services.chat.domain.human_questions.cost import QuestionCost
from service.services.chat.domain.human_questions.resume import QuestionResume
from service.services.chat.infrastructure import question_budget


def material():
    return QuestionResume(
        uuid4(),
        uuid4(),
        uuid4(),
        "ide",
        "model",
        "PRIVATE-REQUEST",
        json.dumps({"generation": "a" * 64}),
        json.dumps([{"role": "tool", "content": "PRIVATE-ANSWER"}]),
    )


def test_cost_receipt_is_closed_frame_bound_and_public_view_does_not_leak_private_material():
    resume = material()
    cost = QuestionCost.quote(resume, 100, required=True)
    assert cost.matches(resume)
    assert not cost.matches(replace(resume, model="other"))
    assert not cost.matches(replace(resume, messages_json="[]"))
    assert not cost.matches(replace(resume, target_json="{}"))
    assert not cost.matches(replace(resume, resume_job_id=uuid4()))
    assert not cost.permits(1)
    accepted = cost.model_copy(update={"state": "accepted", "decided_at": cost.expires_at - 1})
    assert accepted.permits(100) and not accepted.permits(101)
    assert cost.public(now=cost.expires_at)["state"] == "expired"
    assert accepted.public(now=cost.expires_at + 1)["state"] == "accepted"
    assert set(cost.public()) == {"offer_id", "state", "estimated_credits", "expires_at"}
    assert "PRIVATE" not in json.dumps(cost.public()) and "binding" not in cost.public()
    for delta in (
        {"estimated_credits": True},
        {"estimated_credits": -1},
        {"token": "PRIVATE"},
        {"expires_at": float("inf")},
    ):
        with pytest.raises(ValidationError):
            QuestionCost.model_validate({**cost.model_dump(mode="json"), **delta})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "estimate,threshold,approved,required",
    [
        (9, 10, False, False),
        (10, 10, False, True),
        (11, 10, True, False),
        (100, 0, False, False),
    ],
)
async def test_budget_reuses_existing_threshold_and_prices_only_the_pinned_model_frame(
    monkeypatch, estimate, threshold, approved, required
):
    resume = material()
    price = AsyncMock(return_value=estimate)
    billing = SimpleNamespace(expensive_run_confirmation_credits=threshold)
    monkeypatch.setattr(question_budget, "_overlay_billing", lambda *_args: billing)
    monkeypatch.setattr(question_budget, "estimate_reservation_credits", price)
    cost = await question_budget.QuestionBudget(None, None).quote(resume, auto_approved=approved)
    assert cost.state == ("pending" if required else "not_required")
    assert cost.matches(resume)
    assert price.call_args.kwargs["selected_model"] == resume.model
    assert price.call_args.kwargs["context_chars"] == len(resume.messages_json)
    assert price.call_args.kwargs["route"] == "general"
