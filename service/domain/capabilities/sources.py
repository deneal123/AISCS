"""Explicit, source-controlled capability declarations.

There is intentionally no package scanning here. A new built-in capability must be
reviewed as a source-list change, while dynamic MCP tools enter only a run snapshot.
"""

from __future__ import annotations

AGENT_SOURCES = (
    "service.domain.subagents.general",
    "service.domain.subagents.audio_transcribe",
    "service.domain.subagents.web_search",
    "service.domain.subagents.deep_research",
    "service.domain.subagents.image_generation",
    "service.domain.subagents.pdf_generation",
)

WORKFLOW_SOURCES = (
    "service.domain.workflows.research_pdf_presentation",
    "service.domain.workflows.research_pdf_document",
)

TOOL_SOURCES = (
    "service.domain.tools.function_tools",
    "service.domain.tools.web_search_tool",
    "service.domain.tools.workspace_tools",
    "service.domain.tools.latex_tools",
    "service.domain.tools.video_tool",
)

# Dynamic MCP specs use one shared billing contract. It belongs to the compiler input,
# but MCP tool names and schemas never become part of the process-wide static catalog.
DYNAMIC_BILLING_NAMES = frozenset({"mcp_tool"})

__all__ = [
    "AGENT_SOURCES",
    "DYNAMIC_BILLING_NAMES",
    "TOOL_SOURCES",
    "WORKFLOW_SOURCES",
]
