"""Task-bound addressable commands; authorization remains backend-owned."""

import asyncio
import hashlib
import json
import time
from typing import Literal
from uuid import UUID

from application.ide_reads import IdeReadFailure, IdeReadService
from fastapi import APIRouter, Header
from infrastructure.coordinator_client import CoordinationError, _request
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits
from pydantic import BaseModel, ConfigDict, Field

from drivers import DriverError
from presentation.routes.ide_bundle_contracts import CaptureLimits


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str = Field(repr=False)
    task_capability: str = Field(min_length=16, max_length=4096, repr=False)
    operation_id: UUID
    action: Literal["create", "handshake", "dispatch", "status", "stop"]
    engine_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    supervisor: dict | None = Field(default=None, repr=False)
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    limits: CaptureLimits
    argv: list[str] = Field(default_factory=list, max_length=128, repr=False)
    timeout_sec: float = Field(default=60, gt=0, le=120)
    output_limit: int = Field(default=20000, ge=1, le=20000)
    verification_profile: Literal["unittest", "pytest"] | None = None
    verification_target: str | None = Field(default=None, max_length=1024)
    targets: list[str] = Field(default_factory=list, max_length=128)


def create_ide_command_router(deps):
    router = APIRouter(tags=["ide-commands"])

    async def fingerprint(registry, item, limits):
        async with registry.capture_ide(item, BundleLimits(**limits.model_dump())) as capsule:
            return capsule.sha256

    async def permit(payload, workspace_id, *, observed_revision=None):
        data = await _request(
            "/internal/workspace-coordination/ide/command",
            {
                "task_capability": payload.task_capability,
                "operation_id": str(payload.operation_id),
                "workspace_id": workspace_id,
                "action": payload.action,
                "engine_id": payload.engine_id,
                "observed_revision": observed_revision,
                "execution_digest": hashlib.sha256(
                    json.dumps(
                        {
                            "argv": payload.argv,
                            "verification_profile": payload.verification_profile,
                            "verification_target": payload.verification_target,
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "timeout_sec": payload.timeout_sec,
            },
        )
        if data.get("allowed") is not True:
            raise CoordinationError()
        return data

    async def final_sources(registry, item, payload):
        async def run(item, command, *, stdin_payload):
            return await registry.exec_raw(
                item, command, stdin_payload=stdin_payload, max_output_chars=6 * 256 * 1024 + 65536
            )

        facts = {}
        for path in payload.targets:
            try:
                data = await IdeReadService(run).read(item, operation="file", path=path)
                facts[path] = data.get("digest")
            except IdeReadFailure:
                facts[path] = None
        return {"final_revision": await fingerprint(registry, item, payload.limits), "files": facts}

    @router.post("/workspaces/{workspace_id}/ide/commands")
    async def command(
        workspace_id: str, payload: CommandRequest, authorization: str | None = Header(default=None)
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if (
            registry is None
            or item.policy.root != "/workspace"
            or item.policy.user != "65534:65534"
        ):
            return deps.error("workspace_unavailable", "command runtime unavailable", 503)
        try:
            driver = registry.command_driver()
            async with asyncio.timeout(45):
                if payload.action in {"create", "handshake", "dispatch"}:
                    async with registry.operation(item):
                        current, failure = deps.owned(workspace_id, payload)
                        if failure is not None or current is not item:
                            raise DriverError("command_binding_changed")
                        revision = await fingerprint(registry, item, payload.limits)
                        if revision != payload.source_revision:
                            return deps.error("workspace_conflict", "project changed", 409)
                        permitted = await permit(payload, workspace_id, observed_revision=revision)
                        if payload.action == "create":
                            engine_id = await driver.create_command(item.ref, payload.operation_id)
                            return {"engine_id": engine_id, "container_id": item.ref.container_id}
                        if payload.action == "handshake":
                            ready = await driver.ready_command(
                                item.ref, payload.operation_id, payload.engine_id
                            )
                            return {
                                "supervisor": {
                                    key: ready[key] for key in ("pid", "start_time", "version")
                                }
                            }
                        timeout = min(
                            payload.timeout_sec,
                            permitted["timeout_sec"],
                            item.policy.exec_timeout_sec,
                            item.expires_at - time.time(),
                        )
                        if timeout <= 0:
                            raise DriverError("command_expired")
                        await driver.dispatch_command(
                            item.ref,
                            payload.operation_id,
                            payload.engine_id,
                            argv=payload.argv,
                            timeout_sec=timeout,
                            output_limit=min(payload.output_limit, item.policy.max_output_chars),
                            verification_profile=payload.verification_profile,
                            verification_target=payload.verification_target,
                        )
                        return {"running": True}
                permitted = await permit(payload, workspace_id)
                options = {
                    "supervisor": payload.supervisor,
                    "user_start_disallowed": not permitted["dispatch_authorized"],
                }
                method = driver.stop_command if payload.action == "stop" else driver.command_status
                data = await method(item.ref, payload.operation_id, payload.engine_id, **options)
                if not data["running"] and data["cleanup_confirmed"]:
                    async with registry.operation(item):
                        try:
                            data.update(await final_sources(registry, item, payload))
                        except (BundleFailure, DriverError, OSError, ValueError):
                            # Process cleanup and verification of source versions
                            # are separate facts. Retire the gate without claiming
                            # that an unreadable project was successfully verified.
                            data.update(final_revision=None, files={})
                return data
        except (DriverError, CoordinationError, BundleFailure, TimeoutError, ValueError, OSError):
            return deps.error("workspace_unavailable", "command state unavailable", 503)

    return router
