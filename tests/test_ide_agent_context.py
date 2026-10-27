from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.agent_context import (
    build_ide_run_ref,
    resolve_ide_target,
)
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.workspace_collaboration import verify_capability
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import generation_tag
from service.services.chat.infrastructure.chat_worker.engine_env import build_engine_env
from tests.test_ide_edits import setup_runtime
from tests.test_workspace_collaboration import FakeRedis


@pytest.mark.asyncio
async def test_agent_binding_uses_only_owned_repo_generation_and_has_no_client_authority(
    monkeypatch,
):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "tests-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    target = dict(repository_id=str(scope.repository_id), generation=generation_tag(attempt))
    ref = await build_ide_run_ref(
        runtime,
        FakeRedis(),
        thread_id=str(scope.thread_id),
        user_id=str(scope.user_id),
        raw=target,
        run_id=str(uuid4()),
    )
    runtime.resolve.assert_awaited_once_with(scope)
    assert ref["workspace_id"] == "a" * 32
    assert ref["ide_context"]["repository_id"] == str(scope.repository_id)
    capability = verify_capability(ref["coordination_capability"], required_role="agent")
    assert capability.workspace_id == ref["workspace_id"]
    assert "token" not in ref["ide_context"] and "tools_auto_approved" not in ref["ide_context"]


@pytest.mark.asyncio
async def test_missing_foreign_or_stale_target_is_never_replaced_by_a_thread_binding():
    scope, attempt, runtime = setup_runtime()
    target = dict(repository_id=str(scope.repository_id), generation="f" * 64)
    with pytest.raises(IdeEditError, match="ide_generation_changed"):
        await resolve_ide_target(runtime, str(scope.thread_id), str(scope.user_id), target)
    runtime.resolve.side_effect = IdeRepositoryNotFound()
    with pytest.raises(IdeRepositoryNotFound):
        await resolve_ide_target(runtime, str(scope.thread_id), str(scope.user_id), target)
    for injected in ["workspace_id", "token", "user_id", "root", "tools_auto_approved"]:
        with pytest.raises(IdeEditError, match="ide_agent_context_invalid"):
            await resolve_ide_target(
                runtime, str(scope.thread_id), str(scope.user_id), {**target, injected: "PRIVATE"}
            )


@pytest.mark.asyncio
async def test_changed_selected_source_cannot_issue_a_capability():
    scope, attempt, runtime = setup_runtime()
    runtime.client.read = AsyncMock(return_value={"digest": "b" * 64})
    target = dict(
        repository_id=str(scope.repository_id),
        generation=generation_tag(attempt),
        path="main.py",
        digest="c" * 64,
    )
    with pytest.raises(IdeEditError, match="ide_file_changed"):
        await resolve_ide_target(runtime, str(scope.thread_id), str(scope.user_id), target)


@pytest.mark.asyncio
async def test_generation_is_rechecked_after_an_owned_file_read():
    scope, attempt, runtime = setup_runtime()
    runtime.client.read = AsyncMock(return_value={"digest": "b" * 64})
    runtime.runtime.get_owned.return_value = None
    target = dict(
        repository_id=str(scope.repository_id),
        generation=generation_tag(attempt),
        path="main.py",
        digest="b" * 64,
    )
    with pytest.raises(IdeEditError, match="ide_generation_changed"):
        await resolve_ide_target(runtime, str(scope.thread_id), str(scope.user_id), target)


@pytest.mark.asyncio
async def test_engine_env_refuses_ide_without_runtime_composition_and_never_calls_legacy(
    monkeypatch,
):
    from service.infrastructure import workspace_client

    legacy = AsyncMock()
    monkeypatch.setattr(workspace_client, "ensure_workspace", legacy)
    with pytest.raises(IdeEditError, match="ide_agent_context_invalid"):
        await build_engine_env(session_data={"_ide_context": {}}, agent_run_id="run")
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_validates_ide_selection_before_any_reservation(monkeypatch):
    from service.composition import ide
    from service.services.chat.infrastructure.chat_worker.context.targets import (
        validate_run_targets,
    )

    scope, attempt, runtime = setup_runtime()
    runtime.resolve.side_effect = IdeRepositoryNotFound()
    monkeypatch.setattr(ide, "build_ide_runtime", lambda connector: runtime)
    # The composition owner is imported into this helper, not client-provided.
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.context.targets.build_ide_runtime",
        lambda connector: runtime,
    )
    request = SimpleNamespace(
        thread_id=str(scope.thread_id),
        user_id=scope.user_id,
        session_data={
            "_ide_context": dict(
                repository_id=str(scope.repository_id), generation=generation_tag(attempt)
            )
        },
    )
    with pytest.raises(IdeRepositoryNotFound):
        await validate_run_targets(request, FakeRedis(), object())
