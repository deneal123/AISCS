"""Use the existing typed tool kernel, gates, event order and billing seam."""

from __future__ import annotations

import json
from uuid import uuid4

from agents import RunContextWrapper

from service.domain.execution.context import policy_flag
from service.domain.video_summary.source import VideoSummaryFailure


class VideoSummaryTools:
    def __init__(self, agent, context, execution) -> None:
        self.agent = agent
        self.context = context
        self.execution = execution
        self.tool_context = RunContextWrapper(context=context)
        self.round_number = 0
        self.billed: set[str] = set()

    async def execute(self, name: str, arguments: dict):
        spec = self.execution.capabilities.tool(name)
        if spec is None or (
            spec.enabled_field and not self.execution.capabilities.policy.flag(spec.enabled_field)
        ):
            raise VideoSummaryFailure("policy")
        if spec.requires_context_attr and not policy_flag(self.context, spec.requires_context_attr):
            raise VideoSummaryFailure("policy")
        self.round_number += 1
        calls = [{"id": uuid4().hex, "name": name, "arguments": json.dumps(arguments)}]
        convo = []
        failure = None
        async for event in self.agent._execute_tool_round(
            convo,
            calls,
            {name: spec.tool},
            self.tool_context,
            "",
            self.billed,
            round_number=self.round_number,
        ):
            progress = (event.metadata or {}).get("tool_progress") or {}
            if progress.get("status") in {"failed", "invalid", "cancelled"}:
                failure = str(progress.get("failure_code") or "unavailable")
            yield event
        if failure:
            raise VideoSummaryFailure(failure)
        try:
            result = json.loads(convo[-1]["content"]) if name == "ws_write" else None
        except (ValueError, IndexError, KeyError):
            raise VideoSummaryFailure("protocol") from None
        if name == "ws_write" and not (isinstance(result, dict) and result.get("written")):
            raise VideoSummaryFailure("unavailable")
