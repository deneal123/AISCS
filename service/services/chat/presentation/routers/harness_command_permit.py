"""Body-signed workspace callback; only dispatch performs the atomic GO claim."""

import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import get_app_container
from service.services.chat.application.harness_capability import authorize
from service.services.chat.domain.ide.verification import execution_request
from service.services.chat.persistence.harness.commands.recovery import stop_binding
from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
from service.services.chat.presentation.routers.harness_response import private_failure
from service.shared.harness_protocol import HarnessFailure
from service.shared.task_contract import digest_payload

router = APIRouter()


class PermitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_capability: str = Field(min_length=16, max_length=4096, repr=False)
    operation_id: UUID
    workspace_id: str = Field(min_length=1, max_length=128)
    action: Literal["create", "handshake", "dispatch", "status", "stop"]
    engine_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_revision: str | None = Field(default=None, max_length=128)
    execution_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    timeout_sec: float = Field(default=60, gt=0, le=120)


@router.post("/ide/command")
async def command_permit(request: Request):
    from service.services.chat.presentation.routers.workspace_coordination import (
        _authenticated_payload,
    )

    try:
        raw = await _authenticated_payload(
            request,
            request.headers.get("X-Workspace-Timestamp"),
            request.headers.get("X-Workspace-Signature"),
        )
    except HTTPException as error:
        detail: dict = error.detail if isinstance(error.detail, dict) else {}
        code = detail.get("code")
        return private_failure(
            code
            if isinstance(code, str) and code in {"workspace_forbidden", "workspace_unavailable"}
            else "workspace_unavailable",
            error.status_code,
        )
    try:
        if len(raw) > 16384:
            raise ValueError
        payload = PermitBody.model_validate_json(raw)
        owner = authorize(payload.task_capability)
        connector = get_app_container(request).infra.pg_connector
        repository = IdeCommandRepository(connector)
        try:
            record = await repository.command_status(owner, payload.operation_id)
        except HarnessFailure:
            if payload.action != "stop":
                raise
            record = await stop_binding(connector, owner, payload.operation_id)
        timeout = payload.timeout_sec
        if record.workspace_id != payload.workspace_id or record.engine_id != payload.engine_id:
            raise HarnessFailure("binding_changed")
        if payload.action in {"create", "handshake", "dispatch"}:
            if record.source_revision != payload.observed_revision:
                raise HarnessFailure("binding_changed")
            phase = {"create": "creating", "handshake": "handshaking", "dispatch": "waiting"}[
                payload.action
            ]
            if payload.action == "dispatch":
                if record.supervisor is None:
                    raise HarnessFailure("verification_missing")
                if payload.execution_digest != digest_payload(execution_request(record.spec)):
                    raise HarnessFailure("operation_conflict")
                timeout = min(timeout, record.spec.timeout_sec, record.deadline_at - time.time())
                if timeout <= 0:
                    raise HarnessFailure("deadline_exceeded")
                await repository.transition(
                    owner,
                    payload.operation_id,
                    expected_phase=phase,
                    observed_revision=payload.observed_revision,
                    state="running",
                    engine_phase="sent",
                    dispatch_authorized=True,
                )
            else:
                await repository.transition(
                    owner,
                    payload.operation_id,
                    expected_phase=phase,
                    state="ready" if payload.action == "create" else "dispatching",
                )
        return JSONResponse(
            {
                "allowed": True,
                "timeout_sec": timeout,
                "dispatch_authorized": record.dispatch_authorized or payload.action == "dispatch",
            },
            headers={"Cache-Control": "private, no-store"},
        )
    except (ValueError, HarnessFailure) as error:
        code = error.code if isinstance(error, HarnessFailure) else "harness_request_invalid"
        return private_failure(code, 409)
