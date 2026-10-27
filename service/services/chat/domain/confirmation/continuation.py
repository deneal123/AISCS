"""Server-owned continuation choices; browser flags cannot broaden a pending offer."""

from __future__ import annotations

from typing import Any

from service.services.chat.domain.confirmation.offer import (
    ConfirmationOfferAnchor,
    ConfirmationOfferError,
)


def continuation_options(anchor: ConfirmationOfferAnchor, decision: str) -> dict[str, Any]:
    if decision not in {"accept", "decline"}:
        raise ConfirmationOfferError("confirmation_invalid")
    options = dict(anchor.continuation)
    options.update(
        route_override=anchor.route_override,
        resolved_category=anchor.resolved_category,
        watch_video=False,
        confirm_expensive_run=True,
        confirmation_decision=decision,
        confirmation_cancelled=False,
    )
    if decision == "decline":
        options.update(
            route_override="general",
            resolved_category="general",
            web_search=False,
            deep_research=False,
        )
        options["confirmation_cancelled"] = anchor.offer_mode == "expensive_run"
    elif anchor.offer_mode == "expensive_run":
        pass
    elif anchor.offer_kind == "tool":
        if anchor.offer_mode != "watch_video":
            raise ConfirmationOfferError("confirmation_invalid")
        options.update(watch_video=True, route_override="general", resolved_category="general")
    else:
        options.update(
            route_override=anchor.offer_mode,
            resolved_category=anchor.offer_mode,
            deep_research=anchor.offer_mode == "deep_research",
            web_search=anchor.offer_mode == "web_search",
        )
    return options
