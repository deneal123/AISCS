"""In-memory lifecycle registry for isolated workspace containers."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field

import domain.ownership as ownership
from domain.contracts import DEFAULT_TTL_SEC, HARD_TTL_SEC, MAX_WORKSPACES
from domain.policy import WorkspacePolicy
from infrastructure.container_operations import ContainerOperations

from application.recovery import (
    LABEL_MANAGED,
    LABEL_MANIFEST,
    mint_manifest,
    owner_binding,
    parse_manifest,
)
from drivers import ComputeDriver, ContainerRef

logger = logging.getLogger("workspace-sidecar.core")
REAP_INTERVAL_SEC = 30.0
_CLEANUP_BACKOFF_MAX_SEC = 60.0


class WorkspaceNotFound(Exception):
    pass


class TooManyWorkspaces(Exception):
    pass


@dataclass(slots=True)
class Workspace:
    workspace_id: str
    ref: ContainerRef
    policy: WorkspacePolicy
    expires_at: float
    owner_binding: str = ""
    user_id: str = ""
    recovered: bool = False
    created_at: float = field(default_factory=time.time)
    imported: set[str] = field(default_factory=set)
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at


class WorkspaceRegistry:
    """Owns active, reserved and pending-cleanup capacity for this process."""

    def __init__(self, driver: ComputeDriver, *, max_workspaces: int = MAX_WORKSPACES) -> None:
        self._containers = ContainerOperations(driver)
        self._max = max_workspaces
        self._items: dict[str, Workspace] = {}
        self._reserved: set[str] = set()
        self._pending_cleanup: dict[str, tuple[ContainerRef, str, int, float]] = {}
        self._cleanup_counts = {"expired": 0, "legacy": 0, "malformed": 0}
        self._recovered = 0
        self._lock = asyncio.Lock()

    @property
    def driver_name(self) -> str:
        return self._containers.driver_name

    def count(self) -> int:
        return len(self._items) + len(self._reserved) + len(self._pending_cleanup)

    async def create(
        self, user_id: str, policy: WorkspacePolicy, ttl_sec: float = DEFAULT_TTL_SEC
    ) -> tuple[Workspace, str]:
        await self.reap()
        ttl = min(max(1.0, float(ttl_sec)), HARD_TTL_SEC)
        async with self._lock:
            if self.count() >= self._max:
                raise TooManyWorkspaces("workspace capacity reached")
            workspace_id = secrets.token_hex(8)
            self._reserved.add(workspace_id)
        expires_at = time.time() + ttl
        ref: ContainerRef | None = None
        try:
            labels = {
                LABEL_MANAGED: "1",
                LABEL_MANIFEST: mint_manifest(workspace_id, str(user_id), expires_at, policy),
            }
            ref = await self._containers.create(workspace_id, policy, labels)
            await self._containers.verify(ref, policy)
        except Exception:
            async with self._lock:
                self._reserved.discard(workspace_id)
            if ref is not None:
                await self._queue_cleanup(workspace_id, ref, "malformed")
                await self._drain_cleanup()
            raise
        item = Workspace(
            workspace_id=workspace_id,
            ref=ref,
            policy=policy,
            expires_at=expires_at,
            owner_binding=owner_binding(workspace_id, str(user_id)),
            user_id=str(user_id),
        )
        async with self._lock:
            self._reserved.discard(workspace_id)
            self._items[workspace_id] = item
        return item, ownership.mint(workspace_id, str(user_id), ttl_sec=ttl)

    def get(self, workspace_id: str, user_id: str, token: str) -> Workspace:
        ownership.verify(token, str(workspace_id), str(user_id))
        item = self._items.get(str(workspace_id))
        if item is None or item.expired():
            raise WorkspaceNotFound("workspace is unavailable")
        if not hmac.compare_digest(
            item.owner_binding, owner_binding(str(workspace_id), str(user_id))
        ):
            raise WorkspaceNotFound("workspace is unavailable")
        return item

    @contextlib.asynccontextmanager
    async def operation(self, item: Workspace):
        async with item.operation_lock:
            yield item

    async def update_policy(self, item: Workspace, update: dict) -> WorkspacePolicy:
        async with self.operation(item):
            item.policy = item.policy.with_update(update)
            return item.policy

    async def destroy(self, workspace_id: str) -> None:
        async with self._lock:
            item = self._items.pop(str(workspace_id), None)
        if item is None:
            raise WorkspaceNotFound("workspace is unavailable")
        await self._queue_cleanup(item.workspace_id, item.ref, "explicit")
        await self._drain_cleanup()

    async def exec(self, item: Workspace, command: str):
        return await self._containers.exec(
            item.ref,
            command,
            timeout_sec=item.policy.exec_timeout_sec,
            max_output_chars=item.policy.max_output_chars,
        )

    async def exec_raw(
        self,
        item: Workspace,
        command: str,
        *,
        max_output_chars: int,
        stdin_payload: bytes | None = None,
    ):
        return await self._containers.exec(
            item.ref,
            command,
            timeout_sec=item.policy.exec_timeout_sec,
            max_output_chars=max_output_chars,
            stdin_payload=stdin_payload,
        )

    async def _queue_cleanup(self, key: str, ref: ContainerRef, reason: str) -> None:
        async with self._lock:
            self._pending_cleanup.setdefault(key, (ref, reason, 0, 0.0))

    async def _drain_cleanup(self) -> int:
        now = time.time()
        async with self._lock:
            due = [(key, value) for key, value in self._pending_cleanup.items() if value[3] <= now]
        removed = 0
        for key, (ref, reason, attempts, _) in due:
            try:
                await self._containers.destroy(ref)
            except Exception:  # noqa: BLE001
                delay = min(_CLEANUP_BACKOFF_MAX_SEC, 2.0 ** min(attempts + 1, 6))
                async with self._lock:
                    if key in self._pending_cleanup:
                        self._pending_cleanup[key] = (
                            ref,
                            reason,
                            attempts + 1,
                            time.time() + delay,
                        )
                logger.warning("workspace cleanup pending: reason=%s", reason)
            else:
                async with self._lock:
                    self._pending_cleanup.pop(key, None)
                    if reason in self._cleanup_counts:
                        self._cleanup_counts[reason] += 1
                removed += 1
        return removed

    async def reap(self) -> int:
        now = time.time()
        async with self._lock:
            expired = [item for item in self._items.values() if item.expired(now)]
            for item in expired:
                self._items.pop(item.workspace_id, None)
        for item in expired:
            await self._queue_cleanup(item.workspace_id, item.ref, "expired")
        return await self._drain_cleanup()

    async def reconcile(self) -> int:
        found = await self._containers.list_managed()
        if found is None:
            return 0
        now = time.time()
        recovered = 0
        for container in found:
            manifest = parse_manifest(container.labels.get(LABEL_MANIFEST))
            if manifest is None:
                reason = "legacy" if LABEL_MANIFEST not in container.labels else "malformed"
                await self._queue_cleanup(
                    f"cleanup:{container.ref.container_id}", container.ref, reason
                )
                continue
            if manifest.expires_at <= now:
                await self._queue_cleanup(manifest.workspace_id, container.ref, "expired")
                continue
            async with self._lock:
                if (
                    manifest.workspace_id in self._items
                    or manifest.workspace_id in self._pending_cleanup
                ):
                    continue
                self._items[manifest.workspace_id] = Workspace(
                    workspace_id=manifest.workspace_id,
                    ref=container.ref,
                    policy=manifest.policy,
                    expires_at=manifest.expires_at,
                    owner_binding=manifest.owner_binding,
                    recovered=True,
                )
                self._recovered += 1
                recovered += 1
        await self._drain_cleanup()
        return recovered

    def health(self) -> dict[str, object]:
        return {
            "active": len(self._items),
            "recovered": self._recovered,
            "pending_cleanup": len(self._pending_cleanup),
            "expired_cleanup": self._cleanup_counts["expired"],
            "legacy_cleanup": self._cleanup_counts["legacy"] + self._cleanup_counts["malformed"],
            "failure_codes": sorted({entry[1] for entry in self._pending_cleanup.values()}),
        }

    async def active_workspaces(self) -> tuple[Workspace, ...]:
        """Return a stable process-local view for document manifest reconciliation."""

        async with self._lock:
            return tuple(self._items.values())

    async def reap_forever(self, interval_sec: float = REAP_INTERVAL_SEC) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await self.reap()
                await self.reconcile()
            except Exception:  # noqa: BLE001
                logger.error(
                    "workspace maintenance failed",
                    extra={
                        "component": "workspace_lifecycle",
                        "failure_code": "maintenance_failed",
                    },
                )
