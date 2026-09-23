"""Ownership, capability and lifecycle guards shared by workspace routes."""

from __future__ import annotations

import contextlib
import re

from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.application.workspace_collaboration import (
    CollaborationCancelled,
    CollaborationConflict,
    CollaborationError,
    CollaborationForbidden,
    CollaborationPaused,
    WorkspaceCollaborationStore,
    mint_capability,
)

_WORKSPACE_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


async def _ref(service: ChatApplicationService, thread_id: str, user_id: str, redis):
    """Resolve an existing binding after checking thread ownership."""
    await service.ensure_thread_owner(thread_id, user_id)
    ref = await workspace_client.read_binding(redis, thread_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Песочница этому диалогу не выдана")
    return {**ref, "user_id": str(user_id)}


def _collaboration(ref: dict, redis) -> WorkspaceCollaborationStore:
    """Build a TTL-capped store from an ownership-checked binding."""
    expires_at = float(ref.get("expires_at") or 0.0)
    if expires_at <= 0:
        raise HTTPException(status_code=503, detail="Рабочее место временно недоступно")
    return WorkspaceCollaborationStore(
        redis,
        workspace_id=str(ref.get("workspace_id") or ""),
        expires_at=expires_at,
        thread_id=str(ref.get("thread_id") or ""),
    )


def _ui_capability(ref: dict, user_id: str, workspace_session: str | None = None) -> str:
    session = str(workspace_session or "").strip()
    if session and not _WORKSPACE_SESSION_RE.fullmatch(session):
        raise HTTPException(status_code=422, detail="invalid_workspace_session")
    return mint_capability(
        str(ref["workspace_id"]),
        role="ui",
        actor_seed=f"{user_id}:{session or 'legacy'}",
        expires_at=float(ref["expires_at"]),
    )


def _request_ui_capability(ref: dict, user_id: str, workspace_session: str | None) -> str:
    """Use per-browser-session identity while preserving legacy internal callers."""
    if workspace_session:
        return _ui_capability(ref, user_id, workspace_session)
    return _ui_capability(ref, user_id)


def _collaboration_http_error(exc: CollaborationError) -> HTTPException:
    if isinstance(exc, CollaborationConflict):
        return HTTPException(status_code=409, detail="Рабочее место изменилось; обновите данные")
    if isinstance(exc, CollaborationPaused):
        return HTTPException(status_code=423, detail="Работа агента поставлена на паузу")
    if isinstance(exc, CollaborationCancelled):
        return HTTPException(status_code=409, detail="Запуск агента отменён")
    if isinstance(exc, CollaborationForbidden):
        return HTTPException(status_code=403, detail="Нет доступа к рабочему месту")
    return HTTPException(status_code=503, detail="Рабочее место временно недоступно")


async def _request_active_run_cancellation(
    store: WorkspaceCollaborationStore,
    redis,
) -> None:
    """Place the existing cooperative cancellation flag for an active run."""
    task_id = await store.active_agent_run()
    if not task_id:
        return
    try:
        result = redis.set(f"chat:cancel:{task_id}", "1", ex=120)
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:  # noqa: BLE001 - cancellation must remain fail-closed
        raise CollaborationError("workspace cancellation is unavailable") from exc


@contextlib.asynccontextmanager
async def _alive(redis, thread_id: str):
    """Map proven expiry separately from temporary sidecar unavailability."""
    try:
        yield
    except workspace_client.WorkspaceGone as exc:
        await workspace_client.forget_binding(redis, thread_id)
        raise HTTPException(
            status_code=410,
            detail="Песочница этого диалога истекла — следующее сообщение создаст новую",
        ) from exc
    except workspace_client.WorkspaceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Рабочее место временно недоступно; повторите попытку позже",
        ) from exc
