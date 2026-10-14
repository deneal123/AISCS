"""Evict settled in-memory records only after authoritative workspace retirement."""

from __future__ import annotations

import asyncio

from domain.documents import DocumentBuild

SETTLED_STATES = frozenset({"ready", "preview_ready", "visual_pending", "failed", "cancelled"})


def evict_retired_builds(
    builds: dict[str, DocumentBuild],
    tasks: dict[str, asyncio.Task[None]],
    cancel_requested: set[str],
    recovered_workspaces: set[str],
    retained_workspaces: set[str],
) -> None:
    """Caller holds the manager lock; no disk deletion or compiler inference.

    A missing workspace is not permission to forget a live execution or an
    unverified compiler cleanup obligation. Those records keep admission debt.
    Delivered Library artifacts and durable manifests are not modified here.
    """
    recovered_workspaces.intersection_update(retained_workspaces)
    for build_id, build in tuple(builds.items()):
        task = tasks.get(build_id)
        if (
            str(build.workspace_id) in retained_workspaces
            or build.state not in SETTLED_STATES
            or build.compiler_ref
            or (task is not None and not task.done())
        ):
            continue
        builds.pop(build_id)
        tasks.pop(build_id, None)
        cancel_requested.discard(build_id)
