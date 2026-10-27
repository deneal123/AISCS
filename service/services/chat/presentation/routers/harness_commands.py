"""Private task command entry; authentication precedes parsing, never echo bodies."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from service.composition.ide_commands import build_agent_console
from service.composition.state import get_app_container
from service.services.chat.application.harness_capability import authorize, settings
from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
from service.services.chat.presentation.routers.harness_response import private_failure
from service.shared.harness_protocol import Exchange, HarnessFailure

router = APIRouter()
PRIVATE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    action: Literal["run", "status", "stop"]
    operation_id: UUID
    spec: dict | None = None


@router.post("/commands")
async def commands(request: Request):
    try:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or len(header) > 4096:
            raise HarnessFailure("harness_forbidden")
        capability = header[7:]
        owner = authorize(capability)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HarnessFailure("harness_request_invalid")
        try:
            data = RequestBody.model_validate_json(bytes(body))
            if (data.action == "run") != (data.spec is not None):
                raise ValueError
        except ValueError:
            raise HarnessFailure("harness_request_invalid") from None
        spec = None
        if data.action == "run":
            try:
                spec = CommandSpec.model_validate(data.spec)
            except ValueError:
                repository = IdeCommandRepository(get_app_container(request).infra.pg_connector)
                await repository.reject_invalid_command(owner, data.operation_id, data.spec)
                raise HarnessFailure("harness_request_invalid") from None
        if data.action == "run" and not settings().ide_commands_enabled:
            raise HarnessFailure("dispatch_disabled")
        service = build_agent_console(
            get_app_container(request).infra, prepare=data.action == "run"
        )
        if data.action == "run":
            result = await service.run(owner, data.operation_id, spec, capability)
        else:
            result = await service.status(
                owner, data.operation_id, capability, stop=data.action == "stop"
            )
        current = await service.repo.exchange(owner, Exchange(opcode="state"))
        return JSONResponse({"command": result, "snapshot": current["snapshot"]}, headers=PRIVATE)
    except HarnessFailure as error:
        return private_failure(error.code, 403 if error.code == "harness_forbidden" else 409)
    except Exception:
        return private_failure("checkpoint_unavailable", 503)
