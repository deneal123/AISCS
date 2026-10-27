"""Existing pricing/confirmation policy adapted to a pinned tool continuation."""

from service.services.chat.domain.human_questions.cost import QuestionCost
from service.services.chat.domain.human_questions.resume import QuestionResume
from service.services.chat.infrastructure.chat_worker.billing.charging import _overlay_billing
from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
    estimate_reservation_credits,
)


class QuestionBudget:
    def __init__(self, connector, config):
        self.connector = connector
        self.config = config

    async def quote(self, resume: QuestionResume, *, auto_approved: bool = False) -> QuestionCost:
        billing = _overlay_billing(self.connector, self.config)
        estimate = await estimate_reservation_credits(
            pg_connector=self.connector,
            billing_cfg=billing,
            text=resume.text,
            selected_model=resume.model,
            context_chars=len(resume.messages_json),
            route="general",
        )
        threshold = max(0, int(billing.expensive_run_confirmation_credits or 0))
        return QuestionCost.quote(
            resume,
            estimate,
            required=bool(threshold and estimate >= threshold and not auto_approved),
        )
