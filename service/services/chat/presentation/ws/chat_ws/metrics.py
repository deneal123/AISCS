import logging

logger = logging.getLogger(__name__)

_TOOL_KINDS = {"progress", "omission", "offered", "summary", "disclosure"}
_TOOL_STATUSES = {
    "",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "reused",
    "observe",
    "enforce",
    "off",
    "round_cap",
}
_TOOL_REASONS = {
    "",
    "needs_confirmation",
    "not_in_tier",
    "prompt_budget",
    "deadline",
    "timeout",
    "provider_error",
    "invalid_selection",
    "dedup_inflight",
    "dedup_completed",
    "dedup_observed",
    "unknown",
}
_MCP_MODES = {"off", "observe", "enforce"}
_MCP_REASONS = {"ok", "transport", "timeout", "protocol", "remote", "circuit_open", "unknown"}
_WORKFLOW_STATUSES = {"selected", "succeeded", "failed", "unknown"}
_COST_CLASSES = {"cheap", "paid", "expensive", "unknown"}
_RUN_INTEGRITY_REASONS = {
    "invalid_json",
    "invalid_record",
    "mixed_terminal",
    "invalid_result",
    "invalid_error",
    "invalid_event",
    "duplicate_result",
    "result_after_error",
    "error_after_result",
    "event_after_result",
    "unknown",
}
_USAGE_INTEGRITY_REASONS = {"missing_model", "missing_provider", "unknown"}
_GROUNDING_STATES = {"inactive", "pending", "repair", "satisfied", "failed", "unknown"}
_GROUNDING_REASONS = {
    "",
    "cancelled",
    "deadline",
    "internal",
    "invalid_arguments",
    "missing_call",
    "no_eligible_tools",
    "prompt_budget",
    "provider_failure",
    "tool_failure",
    "wrong_call",
    "unknown",
}
_PROVIDERS = {
    "anthropic",
    "deepseek",
    "gigachat",
    "google",
    "mistral",
    "openai",
    "openrouter",
    "qwen",
    "unknown",
}
_PROVIDER_QUALIFICATION_STATUSES = {
    "compatible",
    "compatible_unverified",
    "no_compatible_model",
    "catalog_unavailable",
    "tool_schema",
    "tool_choice",
    "unknown",
}
_STREAM_PROTOCOL_STAGES = {"ndjson", "redis", "websocket", "unknown"}


def _bounded(value: object, allowed: set[str], fallback: str = "unknown") -> str:
    value = str(value or fallback)
    return value if value in allowed else fallback


class ChatWsMetrics:
    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, Histogram

            self.connections_active = Gauge(
                "chat_connections_active", "Number of active chat WebSocket connections"
            )
            self.messages_received_total = Counter(
                "chat_messages_received_total", "Number of messages received via WebSocket"
            )
            self.events_sent_total = Counter(
                "chat_events_sent_total", "Number of events sent to WebSocket clients"
            )
            self.replay_sent_total = Counter(
                "chat_replay_sent_total", "Number of replay entries sent to websocket"
            )
            self.claimed_sent_total = Counter(
                "chat_claimed_sent_total",
                "Number of claimed entries successfully sent to websocket",
            )
            self.claimed_left_unacked_total = Counter(
                "chat_claimed_left_unacked_total",
                "Number of claimed entries that couldn't be sent and left unacked (chat)",
            )
            self.xack_errors_total = Counter(
                "chat_xack_errors_total", "Number of xack errors in chat websocket"
            )
            self.connection_errors_total = Counter(
                "chat_connection_errors_total", "Number of WebSocket connection errors"
            )
            self.tool_lifecycle_total = Counter(
                "agent_tool_lifecycle_total",
                "Agent tool lifecycle events forwarded to chat clients",
                ["kind", "status", "reason"],
            )
            self.tool_duration_seconds = Histogram(
                "agent_tool_duration_seconds",
                "Duration of completed agent tool calls",
                ["status"],
            )
            self.integration_health_total = Counter(
                "agent_integration_health_total",
                "Aggregated agents integration discovery outcomes",
                ["mode", "reason"],
            )
            self.tool_schema_tokens_saved_total = Counter(
                "agent_tool_schema_tokens_saved_total",
                "Actual or observed schema tokens avoided by progressive disclosure",
                ["mode"],
            )
            self.workflow_execution_total = Counter(
                "workflow_catalog_execution_total",
                "Catalog workflow execution outcomes from safe trace metadata",
                ["status", "cost_class"],
            )
            self.run_integrity_total = Counter(
                "agent_run_integrity_total",
                "Protocol anomalies at the agents /run boundary",
                ["reason"],
            )
            self.usage_integrity_total = Counter(
                "agent_usage_integrity_total",
                "Bounded usage-ledger provenance anomalies",
                ["reason"],
            )
            self.grounding_total = Counter(
                "agent_grounding_total",
                "Mandatory tool grounding state transitions",
                ["state", "reason"],
            )
            self.provider_qualification_total = Counter(
                "provider_qualification_total",
                "Provider model capability qualification outcomes",
                ["provider", "status"],
            )
            self.stream_protocol_total = Counter(
                "agent_stream_protocol_total",
                "Bounded stream protocol anomalies",
                ["stage", "reason"],
            )
        except Exception:
            self.connections_active = None
            self.messages_received_total = None
            self.events_sent_total = None
            self.replay_sent_total = None
            self.claimed_sent_total = None
            self.claimed_left_unacked_total = None
            self.xack_errors_total = None
            self.connection_errors_total = None
            self.tool_lifecycle_total = None
            self.tool_duration_seconds = None
            self.integration_health_total = None
            self.tool_schema_tokens_saved_total = None
            self.workflow_execution_total = None
            self.run_integrity_total = None
            self.usage_integrity_total = None
            self.grounding_total = None
            self.provider_qualification_total = None
            self.stream_protocol_total = None

    def inc(self, metric_name: str, value: float = 1.0) -> None:
        metric = getattr(self, metric_name, None)
        if metric is None:
            return
        try:
            if value == 1.0:
                metric.inc()
            else:
                metric.inc(value)
        except Exception:
            logger.debug("metric update failed component=chat_ws code=increment")

    def dec(self, metric_name: str) -> None:
        metric = getattr(self, metric_name, None)
        if metric is None:
            return
        try:
            metric.dec()
        except Exception:
            logger.debug("metric update failed component=chat_ws code=decrement")

    def tool_event(
        self, *, kind: str, status: str = "", reason: str = "", duration_ms=None
    ) -> None:
        """Record bounded labels only; tool names and user data never become metrics labels."""
        try:
            if self.tool_lifecycle_total is not None:
                self.tool_lifecycle_total.labels(
                    kind=_bounded(kind, _TOOL_KINDS),
                    status=_bounded(status, _TOOL_STATUSES, ""),
                    reason=_bounded(reason, _TOOL_REASONS, "unknown"),
                ).inc()
            if duration_ms is not None and self.tool_duration_seconds is not None:
                self.tool_duration_seconds.labels(
                    status=_bounded(status, _TOOL_STATUSES, "")
                ).observe(float(duration_ms) / 1000)
        except Exception:
            logger.debug("metric update failed component=chat_ws code=tool_lifecycle")

    def integration_event(self, *, mode: str, reason: str = "ok", value: int = 1) -> None:
        try:
            if self.integration_health_total is not None:
                self.integration_health_total.labels(
                    mode=_bounded(mode, _MCP_MODES),
                    reason=_bounded(reason, _MCP_REASONS),
                ).inc(max(0, value))
        except Exception:
            logger.debug("metric update failed component=chat_ws code=integration")

    def disclosure_savings(self, *, mode: str, tokens: int) -> None:
        try:
            if self.tool_schema_tokens_saved_total is not None and tokens > 0:
                self.tool_schema_tokens_saved_total.labels(mode=_bounded(mode, _MCP_MODES)).inc(
                    tokens
                )
        except Exception:
            logger.debug("metric update failed component=chat_ws code=disclosure")

    def workflow_execution(self, *, status: str, cost_class: str) -> None:
        try:
            if self.workflow_execution_total is not None:
                self.workflow_execution_total.labels(
                    status=_bounded(status, _WORKFLOW_STATUSES),
                    cost_class=_bounded(cost_class, _COST_CLASSES),
                ).inc()
        except Exception:
            logger.debug("metric update failed component=chat_ws code=workflow")

    def run_integrity(self, *, reason: str, value: int = 1) -> None:
        try:
            if self.run_integrity_total is not None:
                self.run_integrity_total.labels(
                    reason=_bounded(reason, _RUN_INTEGRITY_REASONS)
                ).inc(max(0, value))
        except Exception:
            logger.debug("metric update failed component=chat_ws code=run_integrity")

    def usage_integrity(self, *, reason: str, value: int = 1) -> None:
        try:
            if self.usage_integrity_total is not None:
                self.usage_integrity_total.labels(
                    reason=_bounded(reason, _USAGE_INTEGRITY_REASONS)
                ).inc(max(0, value))
        except Exception:
            logger.debug("Failed to record usage integrity metric")

    def grounding(self, *, state: str, reason: str = "", value: int = 1) -> None:
        try:
            if self.grounding_total is not None:
                bounded_reason = "" if not reason else _bounded(reason, _GROUNDING_REASONS)
                self.grounding_total.labels(
                    state=_bounded(state, _GROUNDING_STATES),
                    reason=bounded_reason,
                ).inc(max(0, value))
        except Exception:
            logger.debug("Failed to record grounding metric")

    def provider_qualification(self, *, provider: str, status: str, value: int = 1) -> None:
        try:
            if self.provider_qualification_total is not None:
                self.provider_qualification_total.labels(
                    provider=_bounded(provider, _PROVIDERS),
                    status=_bounded(status, _PROVIDER_QUALIFICATION_STATUSES),
                ).inc(max(0, value))
        except Exception:
            logger.debug("Failed to record provider qualification metric")

    def stream_protocol(self, *, stage: str, reason: str, value: int = 1) -> None:
        try:
            if self.stream_protocol_total is not None:
                self.stream_protocol_total.labels(
                    stage=_bounded(stage, _STREAM_PROTOCOL_STAGES),
                    reason=_bounded(reason, _RUN_INTEGRITY_REASONS),
                ).inc(max(0, value))
        except Exception:
            logger.debug("Failed to record stream protocol metric")
