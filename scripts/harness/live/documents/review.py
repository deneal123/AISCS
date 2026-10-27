"""Настоящий agents loop с model HTTP double, без автоматического применения."""

import asyncio
import json

from scripts.harness.live.command import admit
from scripts.harness.live.documents.fixture import PATH
from service.infrastructure import workspace_client
from service.infrastructure.agents_client.http_agent_engine import HttpAgentEngine
from service.services.chat.application.documents.context import validate_document_context
from service.services.chat.application.harness_capability import issue
from service.services.chat.application.workspace_collaboration import (
    WorkspaceCollaborationStore,
    mint_capability,
)
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.settings import config
from service.shared.harness_protocol import Exchange

GOAL = (
    "Обнови первый слайд презентации о котиках и добавь слайд о заботе: всего три слайда. "
    "Существующий второй слайд сохрани без изменений."
)


async def propose(container, scope, ref):
    state = await workspace_client.document_authoring_state(ref, path=PATH)
    project = await workspace_client.document_project_status(ref, path=PATH)
    assert state["authoring_version"] == 2 and len(state["draft"]["blocks"]) == 2
    target = await validate_document_context(
        container.infra.redis_client,
        str(scope.thread_id),
        str(scope.user_id),
        {
            "path": PATH,
            "expected_revision": project["revision"],
            "authoring_version": 2,
            "draft_digest": state["draft_digest"],
            "block_ids": ["intro"],
        },
    )
    owner = await admit(
        container,
        scope,
        ref["workspace_id"],
        credits=100000,
        model="GigaChat-3-Lightning",
        goal=GOAL,
        pdf_context=target,
    )
    capability = mint_capability(
        ref["workspace_id"],
        role="agent",
        actor_seed="pdf-acceptance:" + owner.job_id,
        expires_at=ref["expires_at"],
        run_id=owner.job_id,
    )
    await WorkspaceCollaborationStore(
        container.infra.redis_client,
        workspace_id=ref["workspace_id"],
        expires_at=ref["expires_at"],
    ).register_agent_run(owner.job_id)
    reference = {
        **ref,
        "document_context": target,
        "coordination_capability": capability,
        "harness_ref": {"task_id": owner.task_id, "capability": issue(owner)},
    }
    events = []
    async with asyncio.timeout(120):
        result = await HttpAgentEngine(config).execute(
            text=GOAL,
            thread_id=str(scope.thread_id),
            user_id=str(scope.user_id),
            selected_model="GigaChat-3-Lightning",
            route_override="general",
            memory_enabled=False,
            planning=False,
            multi_intent=False,
            workspace_ref=reference,
            provider_policy={
                "disabled": ["openai", "routerai", "openrouter", "mws"],
                "blocked": [],
            },
            on_event=lambda event: events.append(event.model_dump(mode="json")),
        )
    metadata = result["metadata"]
    assert metadata["task_result"]["status"] != "completed"
    assert metadata["task_result"]["unchecked"] == ["slides"]
    assert metadata.get("document_proposal")
    assert await workspace_client.document_authoring_state(ref, path=PATH) == state
    public = json.dumps({"events": events, "result": result})
    for private in (ref["token"], capability, reference["harness_ref"]["capability"]):
        assert private not in public
    current = await HarnessRuntimeRepository(container.infra.pg_connector).exchange(
        owner,
        Exchange(opcode="state"),
    )
    assert current["snapshot"]["held_credits"] == 0
    assert not current["snapshot"]["state"]["evidence"]
    assert current["snapshot"]["state"]["rounds"] == 2
    from scripts.harness.live.documents.continuation import (
        preserve_scope_through_status_writer,
        resume_scope,
    )

    await preserve_scope_through_status_writer(container, owner)
    await resume_scope(container, owner, reference)
    return metadata["document_proposal"], state, project, owner, reference
