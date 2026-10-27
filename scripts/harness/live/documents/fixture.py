"""Собственный PDF-проект с сохранённым соседним слайдом; все изменения через UI API."""

import asyncio
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx

from scripts.harness.live.actors import actor_thread
from service.infrastructure import workspace_client
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.infrastructure.pdf_workspace_binding import publish_pdf_binding
from service.models.key_value import UserTypes
from service.services.chat.domain.ide.runtime import RuntimeAttempt
from service.services.chat.presentation.routers.chat_api.workspace.router import (
    _request_ui_capability,
)
from service.settings import config

PATH = "documents/cats"
SESSION = "pdf-acceptance-" + uuid4().hex


async def post(client, url, body):
    response = await client.post(url, json=body)
    if response.status_code != 200:
        envelope = response.json()
        detail = envelope.get("detail", envelope.get("error"))
        code = detail.get("code") if isinstance(detail, dict) else detail
        allowed = {
            "source_changed",
            "workspace_conflict",
            "authoring_invalid",
            "document_editor_unavailable",
            "authoring_publish_failed",
            "workspace_unavailable",
            "validation_error",
        }
        if isinstance(detail, dict) and detail.get("message") in allowed:
            code = detail["message"]
        print(
            json.dumps(
                {
                    "stage": "pdf_http",
                    "status": response.status_code,
                    "code": code if isinstance(code, str) and code in allowed else None,
                    "operation": url.rsplit("/", 1)[-1],
                }
            ),
            flush=True,
        )
    assert response.status_code == 200, "document_http_request_rejected"
    return response.json()


async def create(container):
    actor, thread = await actor_thread(container)
    scope = SimpleNamespace(user_id=actor, thread_id=thread)
    allocator = IdeWorkspaceClient(config.agents)
    ttl = await allocator.allocation_ttl()
    assert ttl, "pdf_runtime_unavailable"
    attempt = RuntimeAttempt(uuid4(), int(time.time()) + min(ttl, 600), "dispatching", 0)
    observed = await allocator.observe(actor, attempt, create=True, initialize_history=True)
    async with asyncio.timeout(30):
        while observed.state != "ready":
            await asyncio.sleep(0.1)
            observed = await allocator.observe(actor, attempt)
    binding = observed.binding
    assert binding is not None
    ref = {
        "workspace_id": binding.workspace_id,
        "token": binding.token,
        "user_id": str(scope.user_id),
        "thread_id": str(scope.thread_id),
        "root": "/workspace",
        "expires_at": binding.expires_at,
    }
    await publish_pdf_binding(container.infra.redis_client, ref)
    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)
    client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8002",
        timeout=60,
        cookies={"auth_token": token},
        headers={"X-Workspace-Session": SESSION},
    )
    prefix = f"/api/chats/{scope.thread_id}/workspace"
    try:
        lease = await post(client, prefix + "/leases/acquire", {"path": PATH})
        view = await workspace_client.view(ref)
        created = await post(
            client,
            prefix + "/documents",
            {
                "path": PATH,
                "profile_id": "beamer_16_9",
                "mode": "draft",
                "locale": "ru-RU",
                "expected_revision": view["revision"],
                "fence": lease["fence"],
            },
        )
        await post(
            client,
            prefix + "/documents/authoring/edit",
            {
                "path": PATH,
                "draft": {"title": "Котики", "text": "Первоначальный первый слайд."},
                "authoring_version": 0,
                "expected_revision": created["revision"],
                "fence": lease["fence"],
            },
        )
        state = await workspace_client.document_authoring_state(ref, path=PATH)
        project = await workspace_client.document_project_status(ref, path=PATH)
        draft = deepcopy(state["draft"])
        draft["blocks"].append(
            {
                **draft["blocks"][0],
                "block_id": "new_keep",
                "title": "Сохранённый слайд",
                "text": "Этот текст пользователь уже подготовил. Его нельзя менять.",
            }
        )
        await post(
            client,
            prefix + "/documents/authoring/edit",
            {
                "path": PATH,
                "draft": draft,
                "authoring_version": state["authoring_version"],
                "draft_digest": state["draft_digest"],
                "expected_revision": project["revision"],
                "fence": lease["fence"],
            },
        )
        await post(client, prefix + "/leases/release", {"path": PATH, "fence": lease["fence"]})
    except BaseException:
        await client.aclose()
        raise
    return scope, ref, client, prefix


def scoped_ui(ref, user_id):
    return {
        **ref,
        "coordination_capability": _request_ui_capability(ref, str(user_id), SESSION),
    }
