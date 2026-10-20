"""In-memory lifecycle registry for isolated workspace containers."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import domain.ownership as ownership
from domain.contracts import DEFAULT_TTL_SEC, HARD_TTL_SEC, MAX_WORKSPACES
from domain.policy import WorkspacePolicy
from infrastructure.container_operations import ContainerOperations

from application.allocations import AllocationConflict, AllocationPending, WorkspaceAllocation
from application.recovery import (
    LABEL_MANAGED,
    LABEL_MANIFEST,
    RecoveryManifest,
    mint_manifest,
    owner_binding,
    parse_manifest,
)
from drivers import ComputeDriver, ContainerRef, DriverError, IsolationUnverified, ManagedContainer
from drivers.base import (
    ContainerCreationCancelled,
    ContainerCreationFailed,
    ContainerCreationUncertain,
    ContainerCreationUncertainCancelled,
)

if TYPE_CHECKING:
    from application.ide_restore import IdeRestore
    from application.recovery import RestoreSnapshot

logger = logging.getLogger("workspace-sidecar.core")
REAP_INTERVAL_SEC = 30.0
_CLEANUP_BACKOFF_MAX_SEC = 60.0


class WorkspaceNotFound(Exception):
    pass


class WorkspaceCleanupPending(Exception):
    """The exact resource is retired, but physical deletion is not acknowledged."""


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
    restore_snapshot: RestoreSnapshot | None = field(default=None, repr=False)
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
        self._uncertain_creates: dict[str, tuple[float, str]] = {}
        self._recovery_pending: dict[str, Workspace] = {}
        self._pending_cleanup: dict[str, tuple[ContainerRef, str, int, float]] = {}
        self._cleanup_counts = {"expired": 0, "legacy": 0, "malformed": 0}
        self._recovered = 0
        self._lock = asyncio.Lock()

    @property
    def driver_name(self) -> str:
        return self._containers.driver_name

    def count(self) -> int:
        return (
            len(self._items)
            + len(self._reserved)
            + len(self._uncertain_creates)
            + len(self._recovery_pending)
            + len(self._pending_cleanup)
        )

    async def create(
        self,
        user_id: str,
        policy: WorkspacePolicy,
        ttl_sec: float = DEFAULT_TTL_SEC,
        *,
        allocation: WorkspaceAllocation | None = None,
        _restore: IdeRestore | None = None,
    ) -> tuple[Workspace, str]:
        # Validate before reaping/reserving or invoking the driver. The fixed
        # deadline belongs to the persisted backend allocation generation.
        ttl = allocation.remaining() if allocation else min(max(1.0, float(ttl_sec)), HARD_TTL_SEC)
        workspace_id = allocation.workspace_id(user_id) if allocation else secrets.token_hex(8)
        await self.reap()
        async with self._lock:
            if allocation:
                existing = self.lookup_allocation(user_id, allocation)
                if existing:
                    snapshot = _restore.snapshot if _restore else None
                    if existing.policy != policy or existing.restore_snapshot != snapshot:
                        raise AllocationConflict
                    return existing, self.allocation_token(existing, user_id)
            if self.count() >= self._max:
                raise TooManyWorkspaces("workspace capacity reached")
            self._reserved.add(workspace_id)
        expires_at = allocation.expires_at if allocation else time.time() + ttl
        ref: ContainerRef | None = None
        try:
            labels = {
                LABEL_MANAGED: "1",
                LABEL_MANIFEST: mint_manifest(
                    workspace_id,
                    str(user_id),
                    expires_at,
                    policy,
                    **({"restore_snapshot": _restore.snapshot} if _restore else {}),
                ),
            }
            ref = await self._containers.create(workspace_id, policy, labels)
            await self._containers.verify(ref, policy)
            item = Workspace(
                workspace_id=workspace_id,
                ref=ref,
                policy=policy,
                expires_at=expires_at,
                owner_binding=owner_binding(workspace_id, str(user_id)),
                user_id=str(user_id),
                restore_snapshot=_restore.snapshot if _restore else None,
            )
            if _restore is not None:
                await _restore.initialize(self._containers.driver, item, labels[LABEL_MANIFEST])
            # Prepare credentials before publishing an active workspace. A
            # mint failure must not leave a sandbox the caller cannot reach.
            if allocation:
                allocation.remaining()
            token = self.allocation_token(item, user_id)
            async with self._lock:
                if allocation:
                    allocation.remaining()
                self._reserved.discard(workspace_id)
                self._items[workspace_id] = item
        except (Exception, asyncio.CancelledError) as exc:
            uncertain = None
            if isinstance(exc, (ContainerCreationUncertain, ContainerCreationUncertainCancelled)):
                uncertain = (expires_at, labels[LABEL_MANIFEST])
            if isinstance(exc, (ContainerCreationFailed, ContainerCreationCancelled)):
                ref = exc.cleanup_ref
            interrupted = await self._settle_creation_cleanup(
                workspace_id, ref, uncertain=uncertain
            )
            if ref is not None:
                await self._drain_cleanup()
            if interrupted:
                raise asyncio.CancelledError from None
            raise
        return item, token

    async def create_restored(
        self,
        user_id: str,
        policy: WorkspacePolicy,
        *,
        allocation: WorkspaceAllocation,
        source,
        limits,
        expected_size: int,
        expected_sha256: str,
    ) -> tuple[Workspace, str]:
        """Only a fresh selected generation. Never restore into an existing repo."""
        from application.ide_restore import IdeRestore
        from application.recovery import RestoreSnapshot

        snapshot = RestoreSnapshot(expected_sha256, expected_size)
        if (
            not isinstance(allocation, WorkspaceAllocation)
            or policy.root != "/workspace"
            or snapshot.size > limits.archive_bytes
        ):
            raise ValueError("invalid_restore_allocation")
        return await self.create(
            user_id, policy, allocation=allocation, _restore=IdeRestore(source, snapshot, limits)
        )

    def lookup_allocation(self, user_id: str, allocation: WorkspaceAllocation) -> Workspace | None:
        """Read only: no Docker inventory, allocation, Git init or TTL refresh."""
        allocation.remaining()
        key = allocation.workspace_id(user_id)
        if (
            key in self._reserved
            or key in self._uncertain_creates
            or key in self._recovery_pending
            or key in self._pending_cleanup
        ):
            raise AllocationPending
        item = self._items.get(key)
        if item is None:
            return None
        if item.expires_at != allocation.expires_at or not hmac.compare_digest(
            item.owner_binding, owner_binding(key, str(user_id))
        ):
            raise AllocationConflict
        return item

    @staticmethod
    def allocation_token(item: Workspace, user_id: str) -> str:
        return ownership.mint(
            item.workspace_id, str(user_id), ttl_sec=item.expires_at - time.time()
        )

    async def _settle_creation_cleanup(
        self,
        workspace_id: str,
        ref: ContainerRef | None,
        *,
        uncertain: tuple[float, str] | None = None,
    ) -> bool:
        # Shield only the in-memory handoff, never Docker I/O. Lock owners do
        # not await external operations while holding this registry lock.
        retirement = (
            self._retire_failed_creation(workspace_id, ref)
            if uncertain is None
            else self._retire_failed_creation(workspace_id, ref, uncertain=uncertain)
        )
        handoff = asyncio.create_task(retirement)
        interrupted = False
        while True:
            try:
                await asyncio.shield(handoff)
                return interrupted
            except asyncio.CancelledError:
                if handoff.cancelled():
                    # Process shutdown can cancel child tasks too; do not spin
                    # on a terminal cancelled handoff. Restart uses manifests.
                    raise
                interrupted = True

    async def _retire_failed_creation(
        self,
        workspace_id: str,
        ref: ContainerRef | None,
        *,
        uncertain: tuple[float, str] | None = None,
    ) -> None:
        async with self._lock:
            self._reserved.discard(workspace_id)
            if uncertain is not None:
                self._uncertain_creates.setdefault(workspace_id, uncertain)
            if ref is not None:
                self._pending_cleanup.setdefault(workspace_id, (ref, "malformed", 0, 0.0))

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

    def authorize_cleanup(self, workspace_id: str, user_id: str, token: str) -> None:
        """A valid owner can retry the same cleanup debt without reviving access."""
        key = str(workspace_id)
        ownership.verify(token, key, str(user_id))
        item = self._items.get(key) or self._recovery_pending.get(key)
        if item is not None:
            if not hmac.compare_digest(item.owner_binding, owner_binding(key, str(user_id))):
                raise ownership.OwnershipError("workspace ownership mismatch")
            return
        if key in self._pending_cleanup:
            return
        if key in self._reserved or key in self._uncertain_creates:
            raise WorkspaceCleanupPending
        raise WorkspaceNotFound("workspace is unavailable")

    @contextlib.asynccontextmanager
    async def operation(self, item: Workspace):
        async with item.operation_lock:
            yield item

    async def update_policy(
        self,
        item: Workspace,
        update: dict,
        *,
        before_update: Callable[[], Awaitable[None]] | None = None,
    ) -> WorkspacePolicy:
        async with self.operation(item):
            if before_update is not None:
                await before_update()
            item.policy = item.policy.with_update(update)
            return item.policy

    async def destroy(self, workspace_id: str) -> bool:
        key = str(workspace_id)
        async with self._lock:
            item = self._items.pop(key, None) or self._recovery_pending.pop(key, None)
            if item is None and key not in self._pending_cleanup:
                raise WorkspaceNotFound("workspace is unavailable")
            # Ownership retirement and cleanup capacity are one state change.
            # Cancellation during the subsequent driver call must retain debt.
            if item is not None:
                self._pending_cleanup.setdefault(key, (item.ref, "explicit", 0, 0.0))
        await self._drain_cleanup()
        async with self._lock:
            return not any(
                key in entries
                for entries in (
                    self._items,
                    self._reserved,
                    self._uncertain_creates,
                    self._recovery_pending,
                    self._pending_cleanup,
                )
            )

    async def exec(self, item: Workspace, command: str):
        return await self._containers.exec(
            item.ref,
            command,
            timeout_sec=item.policy.exec_timeout_sec,
            max_output_chars=item.policy.max_output_chars,
        )

    async def git_ide(self, item: Workspace, **kwargs):
        from application.ide_git import run_git

        return await run_git(self._containers.driver, item, **kwargs)

    def capture_ide(self, item: Workspace, limits):
        from application.ide_bundles import IdeBundleService

        # The caller owns operation_lock and checks ownership/coordination on
        # both sides of capture. The helper never mutates repository contents.
        return IdeBundleService(self._containers.driver).capture_verified(item, limits)

    def command_driver(self):
        driver = self._containers.driver
        if not all(
            callable(getattr(driver, name, None))
            for name in (
                "create_command",
                "ready_command",
                "dispatch_command",
                "command_status",
                "stop_command",
            )
        ):
            raise DriverError("command_driver_unavailable")
        return driver

    async def move_ide(self, item: Workspace, **kwargs):
        from application.ide_moves import move_file

        return await move_file(self._containers.driver, item, **kwargs)

    async def write_ide(self, item: Workspace, **kwargs):
        from application.ide_writes import IdeWriteService

        # The route owns operation_lock and the authenticated coordinator fence.
        return await IdeWriteService(self._containers.driver).write(item, **kwargs)

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
            self._recovery_pending.pop(key, None)
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
                self._pending_cleanup.setdefault(item.workspace_id, (item.ref, "expired", 0, 0.0))
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
            async with self._lock:
                if manifest.workspace_id in self._reserved:
                    # A create still in flight has not transferred ownership.
                    continue
                uncertain = self._uncertain_creates.get(manifest.workspace_id)
                if uncertain is not None:
                    if hmac.compare_digest(uncertain[1], container.labels[LABEL_MANIFEST]):
                        self._uncertain_creates.pop(manifest.workspace_id)
                        self._pending_cleanup.setdefault(
                            manifest.workspace_id, (container.ref, "malformed", 0, 0.0)
                        )
                    # Never adopt or delete another signed manifest on ID alone.
                    continue
            if manifest.expires_at <= now:
                await self._queue_cleanup(manifest.workspace_id, container.ref, "expired")
                continue
            if await self._recover_verified(container, manifest):
                recovered += 1
        async with self._lock:
            # A successful inventory plus expiry retires invisible intents.
            # Late daemon commits retain an expired signature and are reaped later.
            for key, (expires_at, _) in tuple(self._uncertain_creates.items()):
                if expires_at <= now:
                    self._uncertain_creates.pop(key)
            for key, item in tuple(self._recovery_pending.items()):
                if item.expired(now):
                    self._recovery_pending.pop(key)
                    self._pending_cleanup.setdefault(key, (item.ref, "expired", 0, 0.0))
        await self._drain_cleanup()
        return recovered

    async def _recover_verified(
        self, container: ManagedContainer, manifest: RecoveryManifest
    ) -> bool:
        key = manifest.workspace_id
        async with self._lock:
            if (
                key in self._items
                or key in self._reserved
                or key in self._uncertain_creates
                or key in self._pending_cleanup
            ):
                return False
            pending = self._recovery_pending.get(key)
            if pending is not None and pending.ref != container.ref:
                return False
            item = pending or Workspace(
                workspace_id=key,
                ref=container.ref,
                policy=manifest.policy,
                expires_at=manifest.expires_at,
                owner_binding=manifest.owner_binding,
                recovered=True,
                restore_snapshot=getattr(manifest, "restore_snapshot", None),
            )
            # Retain capacity even if inspection is interrupted or unavailable.
            self._recovery_pending.setdefault(key, item)
        try:
            await self._containers.verify(container.ref, manifest.policy)
            if item.restore_snapshot is not None:
                from application.ide_bundles import IdeBundleService
                from application.recovery import restore_receipt

                ready = await IdeBundleService(self._containers.driver).receipt(
                    item, restore_receipt(container.labels[LABEL_MANIFEST]), write=False
                )
                if not ready:
                    await self._queue_cleanup(key, container.ref, "restore_incomplete")
                    return False
        except IsolationUnverified:
            await self._queue_cleanup(key, container.ref, "isolation")
            return False
        except Exception:
            logger.warning(
                "workspace recovery inspection unavailable",
                extra={
                    "component": "workspace_lifecycle",
                    "failure_code": "inspection_unavailable",
                },
            )
            return False
        async with self._lock:
            if (
                key in self._items
                or key in self._pending_cleanup
                or key in self._reserved
                or key in self._uncertain_creates
                or self._recovery_pending.get(key) is not item
            ):
                return False
            self._recovery_pending.pop(key, None)
            if item.expired():
                self._pending_cleanup.setdefault(key, (item.ref, "expired", 0, 0.0))
                return False
            self._items[key] = item
            self._recovered += 1
        return True

    def health(self) -> dict[str, object]:
        return {
            "active": len(self._items),
            "recovered": self._recovered,
            "pending_cleanup": len(self._pending_cleanup),
            "creation_pending": len(self._uncertain_creates),
            "recovery_pending": len(self._recovery_pending),
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
