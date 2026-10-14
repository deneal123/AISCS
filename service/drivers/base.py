"""Шов драйвера вычислений: чем именно исполняется песочница.

⚠️ ЗАЧЕМ ШОВ СРАЗУ, А НЕ ПОТОМ. Сегодня песочница — контейнер docker, и этого достаточно.
Завтра прод захочет границу прочнее (gVisor, Firecracker, отдельный узел Kubernetes) — и
без шва такая замена переписывает и слой инструментов, и контракт. Заложенный на старте, он
стоит один протокол; добавленный позже — миграцию. Приём взят у OpenShell (docker/podman/
microvm/k8s за одним интерфейсом), сам рантайм — нет.

🔴 `verify_isolation` В ПРОТОКОЛЕ, А НЕ В РЕАЛИЗАЦИИ. Драйвер обязан уметь ПОДТВЕРДИТЬ
изоляцию, а не только заявить о ней при создании: незаверенное заявление о песочнице
однажды разойдётся с фактом — из-за флага демона, версии рантайма или чужой правки
compose, — и разойдётся молча.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from domain.policy import WorkspacePolicy


class DriverError(Exception):
    """Рантайм не смог выполнить операцию."""


class IsolationUnverified(Exception):
    """Заявленная изоляция не подтвердилась. Песочница обязана быть уничтожена."""


@dataclass(frozen=True, slots=True)
class ContainerRef:
    """Ссылка на исполнителя. Содержимое непрозрачно для всех, кроме своего драйвера."""

    driver: str
    container_id: str


class ContainerCreationFailed(DriverError):
    """Private cleanup debt; never serialized into the public error response."""

    def __init__(self, cleanup_ref: ContainerRef | None) -> None:
        super().__init__("container start failed")
        self.cleanup_ref = cleanup_ref


class ContainerCreationCancelled(asyncio.CancelledError):
    """Preserves cancellation semantics while handing cleanup debt to the registry."""

    def __init__(self, cleanup_ref: ContainerRef | None) -> None:
        super().__init__()
        self.cleanup_ref = cleanup_ref


class ContainerCreationUncertain(DriverError):
    """Create response was lost; no container ID or non-creation proof is available."""

    def __init__(self) -> None:
        super().__init__("container creation uncertain")


class ContainerCreationUncertainCancelled(asyncio.CancelledError):
    """Cancellation after submitting create requires ownership reconciliation."""


@dataclass(frozen=True, slots=True)
class ManagedContainer:
    ref: ContainerRef
    labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    duration_sec: float
    timed_out: bool = False


@runtime_checkable
class ComputeDriver(Protocol):
    """Минимум, которого хватает слою инструментов. Всё остальное — дело драйвера."""

    name: str

    async def create(
        self, workspace_id: str, policy: WorkspacePolicy, *, labels: dict[str, str] | None = None
    ) -> ContainerRef: ...

    async def list_managed(self) -> list[ManagedContainer]: ...

    async def verify_isolation(self, ref: ContainerRef, policy: WorkspacePolicy) -> None:
        """Подтвердить фактическое состояние. Расхождение — `IsolationUnverified`."""
        ...

    async def exec(
        self, ref: ContainerRef, command: str, *, timeout_sec: float, max_output_chars: int
    ) -> ExecResult: ...

    async def destroy(self, ref: ContainerRef) -> None: ...
