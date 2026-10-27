"""Resolve an IDE run to an existing owned generation, never the chat/PDF binding."""

import time
from typing import Any
from uuid import UUID

from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.application.workspace_collaboration import (
    WorkspaceCollaborationStore,
    mint_capability,
)
from service.services.chat.domain.ide.agent_context import IdeAgentContext
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    ResolvedRuntime,
    generation_tag,
)


async def resolve_ide_target(
    runtime: IdeRuntimeService, thread_id: str, user_id: str, raw: Any
) -> tuple[IdeAgentContext, ResolvedRuntime]:
    try:
        target = IdeAgentContext.model_validate(raw)
        scope = RepositoryScope(UUID(thread_id), UUID(user_id), target.repository_id)
    except (ValueError, TypeError):
        raise IdeEditError("ide_agent_context_invalid") from None
    resolved = await runtime.resolve(scope)
    if generation_tag(resolved.attempt) != target.generation:
        raise IdeEditError("ide_generation_changed")
    if target.path is not None:
        file = await runtime.client.read(
            scope.user_id, resolved.binding, operation="file", path=target.path
        )
        if target.digest is not None and file.get("digest") != target.digest:
            raise IdeEditError("ide_file_changed")
    # Resolve once more after the read, so a changed/expired runtime cannot issue
    # a capability for a stale selection after a delayed file response.
    current = await runtime.runtime.get_owned(scope)
    if current is None or current.allocation_id != resolved.attempt.allocation_id:
        raise IdeEditError("ide_generation_changed")
    if current.expires_at <= time.time():
        raise IdeEditError("ide_runtime_expired")
    if current.state != "ready":
        raise IdeEditError("ide_runtime_not_ready")
    return target, ResolvedRuntime(current, resolved.binding)


async def build_ide_run_ref(
    runtime: IdeRuntimeService, redis: Any, *, thread_id: str, user_id: str, raw: Any, run_id: str
) -> dict[str, Any]:
    if not run_id:
        raise IdeEditError("ide_agent_context_invalid")
    target, resolved = await resolve_ide_target(runtime, thread_id, user_id, raw)
    binding = resolved.binding
    capability = mint_capability(
        binding.workspace_id,
        role="agent",
        actor_seed=f"ide:{thread_id}:{user_id}:{run_id}",
        expires_at=binding.expires_at,
        run_id=run_id,
    )
    store = WorkspaceCollaborationStore(
        redis, workspace_id=binding.workspace_id, expires_at=binding.expires_at
    )
    await store.register_agent_run(run_id)
    from service.services.chat.application.harness_capability import settings

    flags = settings()
    return dict(
        workspace_id=binding.workspace_id,
        token=binding.token,
        user_id=user_id,
        expires_at=binding.expires_at,
        root="/workspace",
        coordination_capability=capability,
        ide_context=target.model_dump(mode="json"),
        ide_commands_enabled=flags.ide_enabled
        and flags.ide_commands_enabled
        and flags.dispatch_enabled,
    )
