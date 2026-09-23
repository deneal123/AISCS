"""Read-only client for the user's Graphify knowledge graph."""

from __future__ import annotations

import logging

from service.infrastructure.sidecar import SidecarClient
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)


class GraphifyClient:
    """Graph search is best effort: unavailable or empty graph yields no context."""

    def __init__(self) -> None:
        self._base = (config.agents.graphify_url or "").rstrip("/")
        self._client = SidecarClient(service="graphify", base_url=self._base, timeout=60.0)

    @property
    def enabled(self) -> bool:
        return bool(
            runtime_settings.get_agents("graphify_enabled", config.agents.graphify_enabled)
            and self._client.available
        )

    async def query(
        self, question: str, *, graph_id: str, depth: int = 3, token_budget: int = 2000
    ) -> str:
        if not self.enabled or not question.strip():
            return ""
        try:
            body = await self._client.request_json(
                "POST",
                "/graph/query",
                params={"graph_id": graph_id},
                json_body={
                    "question": question,
                    "depth": depth,
                    "token_budget": token_budget,
                },
            )
            return str(body.get("context") or "").strip()
        except Exception:
            logger.warning("graphify query failed code=unavailable")
            return ""


def user_graph_id(user_id: str) -> str:
    """Stable, path-safe identifier of a user's private graph."""
    safe = "".join(c for c in str(user_id or "") if c.isalnum() or c in "-_")
    return f"user-{safe}" if safe else ""
