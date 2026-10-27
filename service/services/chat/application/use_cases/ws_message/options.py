"""Pure WS message normalization and explicit worker/fallback projections.

No identity, offer claim, routing call, job ID or queue authority lives here.
Continuation choices come only from the server anchor. Workspace bindings must
be supplied separately by admission, never copied from browser session_data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from service.services.chat.application.use_cases.ws_message.admission import WsAdmission, WsRoute
from service.services.chat.domain.confirmation.continuation import continuation_options
from service.services.chat.domain.confirmation.offer import ConfirmationOfferAnchor


def _optional_bool(value: Any) -> bool | None:
    """None keeps the admin default; false is an explicit user choice."""
    return None if value is None else bool(value)


@dataclass(frozen=True, slots=True, repr=False)
class WsMessageOptions:
    text: str | None
    message_id: Any
    route: WsRoute
    file_context: str
    attachments: list[Any] | None
    file_ids: list[Any] | None
    memory_enabled: bool
    ldr_model: str | None
    ldr_strategy: str | None
    multi_intent: bool | None
    planning: bool | None
    persona_ids: list[str] | None
    detach_files: bool
    watch_video: bool
    confirm_expensive_run: bool
    confirmed_offer_id: str | None
    confirmation_decision: str | None
    confirmation_cancelled: bool = False

    @classmethod
    def from_message(
        cls,
        msg: dict[str, Any],
        *,
        anchor: ConfirmationOfferAnchor | None,
        offer_id: str,
        decision: str,
    ) -> WsMessageOptions:
        """Normalize fresh options or restore canonical offer content before admission."""
        raw_personas = msg.get("persona_ids")
        return cls(
            text=anchor.text if anchor else msg.get("text"),
            message_id=msg.get("id"),
            route=WsRoute(
                selected_model=anchor.selected_model if anchor else msg.get("model"),
                input_type=anchor.input_type if anchor else msg.get("input_type"),
                route_override=anchor.route_override if anchor else msg.get("route_override"),
                web_search=False if anchor else bool(msg.get("web_search", False)),
                deep_research=False if anchor else bool(msg.get("deep_research", False)),
                resolved_category=anchor.resolved_category if anchor else None,
            ),
            file_context="" if anchor else msg.get("file_context", ""),
            attachments=list(anchor.attachments) if anchor else (msg.get("attachments") or None),
            file_ids=list(anchor.file_ids)
            if anchor
            else (msg.get("file_ids") if isinstance(msg.get("file_ids"), list) else None),
            memory_enabled=bool(msg.get("memory_enabled", True)),
            # Provider registry/strategy validation belongs to agents, not WS parsing.
            ldr_model=msg.get("ldr_model") or None,
            ldr_strategy=msg.get("ldr_strategy") or None,
            multi_intent=_optional_bool(msg.get("multi_intent")),
            planning=_optional_bool(msg.get("planning")),
            persona_ids=[str(p) for p in raw_personas if str(p).strip()]
            if isinstance(raw_personas, list)
            else None,
            detach_files=bool(msg.get("detach_files")),
            watch_video=bool(msg.get("watch_video")),
            confirm_expensive_run=bool(anchor) or bool(msg.get("confirm_expensive_run")),
            confirmed_offer_id=offer_id or None,
            confirmation_decision=decision if anchor else None,
        )

    def after_admission(
        self,
        admission: WsAdmission,
        *,
        anchor: ConfirmationOfferAnchor | None,
        decision: str,
    ) -> WsMessageOptions:
        """Apply server-owned continuation choices only after workspace validation."""
        route = admission.route
        options = self
        if anchor is not None:
            continuation = continuation_options(anchor, decision)
            route = replace(
                route,
                route_override=continuation["route_override"],
                resolved_category=continuation["resolved_category"],
                web_search=bool(continuation.get("web_search")),
                deep_research=bool(continuation.get("deep_research")),
            )
            options = replace(
                options,
                watch_video=continuation["watch_video"],
                file_context=continuation.get("file_context", ""),
                planning=continuation.get("planning"),
                multi_intent=continuation.get("multi_intent"),
                persona_ids=continuation.get("persona_ids"),
                memory_enabled=bool(continuation.get("memory_enabled", True)),
                confirmation_cancelled=bool(continuation.get("confirmation_cancelled")),
            )
        if admission.ide_context:
            route = replace(route, route_override="general", resolved_category="general")
        return replace(options, route=route)

    def worker_options(self, thread_id: str, admission: WsAdmission) -> dict[str, Any]:
        """Closed payload keys: caller still owns authenticated identity/job/queue."""
        return {
            "session_data": {
                **({"_ide_context": admission.ide_context} if admission.ide_context else {}),
                **(
                    {"_document_context": admission.document_context}
                    if admission.document_context
                    else {}
                ),
                "session_id": thread_id,
                "file_ids": self.file_ids,
                "detach_files": self.detach_files,
                "watch_video": self.watch_video,
                "confirm_expensive_run": self.confirm_expensive_run,
                "confirmed_offer_id": self.confirmed_offer_id,
                "confirmation_decision": self.confirmation_decision,
                "confirmation_cancelled": self.confirmation_cancelled,
                "_routing_usage": self.route.routing_usage,
                "_resolved_category": self.route.resolved_category,
            },
            "selected_model": self.route.selected_model,
            "route_override": self.route.route_override,
            "input_type": self.route.input_type,
            "web_search": self.route.web_search,
            "deep_research": self.route.deep_research,
            "file_context": self.file_context,
            "attachments": self.attachments,
            "memory_enabled": self.memory_enabled,
            "ldr_model": self.ldr_model,
            "ldr_strategy": self.ldr_strategy,
            "multi_intent": self.multi_intent,
            "planning": self.planning,
            "persona_ids": self.persona_ids,
        }

    def fallback_options(self) -> dict[str, Any]:
        """Preserve the legacy REST fallback contract; do not expand its permissions."""
        return {
            "selected_model": self.route.selected_model,
            "input_type": self.route.input_type,
            "web_search": self.route.web_search,
            "deep_research": self.route.deep_research,
            "file_context": self.file_context,
            "attachments": self.attachments,
            "route_override": self.route.route_override,
            "routing_metadata": None,
            "confirm_expensive_run": self.confirm_expensive_run,
        }
