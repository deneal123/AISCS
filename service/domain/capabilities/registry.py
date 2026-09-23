"""Compatibility facade over the process-wide compiled capability catalog."""

from __future__ import annotations

from .compiler import compile_static_catalog
from .metrics import record
from .runtime import get_static_catalog
from .sources import AGENT_SOURCES, TOOL_SOURCES, WORKFLOW_SOURCES

# Kept mutable only for legacy tests that prove one-place registration. Production
# compilation reads the canonical tuples from ``sources`` and runs once at startup.
_AGENT_SOURCES = AGENT_SOURCES
_WORKFLOW_SOURCES = WORKFLOW_SOURCES


class CapabilityBuildError(RuntimeError):
    code = "capability_build"

    def __init__(self):
        super().__init__(self.code)


def _catalog():
    from service.domain.run_context import current_execution

    if _AGENT_SOURCES != AGENT_SOURCES or _WORKFLOW_SOURCES != WORKFLOW_SOURCES:
        # Isolated compatibility path for tests/internal callers injecting a synthetic
        # source. It cannot alter the active process catalog or its billing contract.
        return compile_static_catalog(
            agent_sources=_AGENT_SOURCES,
            workflow_sources=_WORKFLOW_SOURCES,
            tool_sources=TOOL_SOURCES,
            billable_contract=None,
        )
    execution = current_execution()
    if execution is not None:
        return execution.capabilities.static
    return get_static_catalog()


def agent_specs() -> dict:
    return dict(_catalog().agents)


def workflow_specs() -> dict:
    return dict(_catalog().workflows)


def get_spec(name: str):
    return _catalog().agents.get(str(name or "").strip().lower())


def get_workflow(name: str):
    return _catalog().workflows.get(str(name or "").strip().lower())


def build_agents(model_settings: dict | None = None) -> dict:
    settings = model_settings or {}
    built = {}
    for spec in _catalog().agents.values():
        try:
            built[spec.name] = spec.build(settings)
        except Exception:  # noqa: BLE001 - factories may wrap provider SDKs
            record("build", "failed", "capability_build")
            raise CapabilityBuildError() from None
    record("build", "ok")
    return built


__all__ = [
    "CapabilityBuildError",
    "agent_specs",
    "build_agents",
    "get_spec",
    "get_workflow",
    "workflow_specs",
]
