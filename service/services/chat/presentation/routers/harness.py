"""Private acknowledged exchanges. Authentication precedes body validation."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from service.composition.state import get_app_container
from service.services.chat.application.harness_capability import authorize
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.services.chat.presentation.routers.harness_commands import router as commands_router
from service.services.chat.presentation.routers.harness_response import private_failure
from service.shared.harness_protocol import Exchange, HarnessFailure

router = APIRouter(prefix="/internal/harness/v1", include_in_schema=False)
router.include_router(commands_router)
PRIVATE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


@router.post("/exchange")
async def exchange(request: Request):
    try:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or len(header) > 4096:
            raise HarnessFailure("harness_forbidden")
        owner = authorize(header[7:])
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1048576:
                raise HarnessFailure("checkpoint_too_large")
        try:
            payload = Exchange.model_validate_json(bytes(body))
        except ValueError:
            raise HarnessFailure("harness_request_invalid") from None
        connector = get_app_container(request).infra.pg_connector
        result = await HarnessRuntimeRepository(connector).exchange(owner, payload)
        return JSONResponse(result, headers=PRIVATE)
    except HarnessFailure as error:
        status = 403 if error.code == "harness_forbidden" else 409
        if error.code == "checkpoint_unavailable":
            status = 503
        return private_failure(error.code, status)
