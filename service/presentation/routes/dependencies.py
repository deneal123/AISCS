"""Dependency bundle used by private workspace route factories.

Callbacks intentionally remain late-bound in ``workspace_routes``.  That keeps
the legacy direct-handler test seam stable while production gets independently
composable routers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class WorkspaceRouteDependencies:
    auth: Callable[[str | None], None]
    error: Callable[[str, str, int], JSONResponse]
    registry: Callable[[], Any]
    owned: Callable[[str, Any], tuple[Any | None, JSONResponse | None]]
    coordination_guard: Callable[..., Awaitable[Any]]
    guard_denied: Callable[[Any], bool]
    run_file_op: Callable[..., Awaitable[Any]]
    revision: Callable[[Any], Awaitable[str]]
    snapshot: Callable[[Any, str], Awaitable[dict]]
    fetch: Callable[..., Awaitable[bytes]]
