"""One cost decision bound to the exact private, already answered continuation."""

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from service.services.chat.domain.confirmation.offer import OFFER_TTL_SEC

COST_KEY = "_human_question_cost_v1"


def cost_binding(resume: Any) -> str:
    value = [
        str(resume.resume_job_id),
        resume.model,
        resume.text,
        json.loads(resume.target_json),
        json.loads(resume.messages_json),
    ]
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class QuestionCost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    offer_id: UUID
    state: Literal["pending", "accepted", "declined", "not_required"]
    estimated_credits: int = Field(strict=True, ge=0)
    binding: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: float = Field(strict=True, allow_inf_nan=False, gt=0)
    decided_at: float | None = Field(default=None, strict=True, allow_inf_nan=False, gt=0)

    @model_validator(mode="after")
    def decision_receipt(self):
        if not self.offer_id.int or (
            (self.state in {"accepted", "declined"}) != (self.decided_at is not None)
        ):
            raise ValueError("human_question_invalid")
        if self.state == "accepted" and self.decided_at >= self.expires_at:
            raise ValueError("human_question_invalid")
        return self

    @classmethod
    def quote(cls, resume: Any, estimate: int, *, required: bool, offer_id: UUID | None = None):
        return cls(
            offer_id=offer_id or uuid4(),
            state="pending" if required else "not_required",
            estimated_credits=estimate,
            binding=cost_binding(resume),
            expires_at=time.time() + OFFER_TTL_SEC,
        )

    def matches(self, resume: Any) -> bool:
        return bool(self.offer_id.int and self.binding == cost_binding(resume))

    def permits(self, estimate: int) -> bool:
        return (
            self.state == "accepted"
            and self.decided_at is not None
            and estimate <= self.estimated_credits
        )

    def public(self, *, now: float | None = None) -> dict:
        state = self.state
        if state == "pending" and self.expires_at <= (time.time() if now is None else now):
            state = "expired"
        return {
            "offer_id": str(self.offer_id),
            "state": state,
            "estimated_credits": self.estimated_credits,
            "expires_at": datetime.fromtimestamp(self.expires_at, UTC).isoformat(),
        }
