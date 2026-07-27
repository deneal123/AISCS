"""Реестр песочниц: жизненный цикл, срок жизни, владение.

Состояние живёт В ПАМЯТИ процесса намеренно: песочница привязана к контейнеру на ЭТОМ
хосте, и вторая копия сервиса всё равно не смогла бы её исполнить. Общая БД создавала бы
видимость переносимости, которой нет.

🔴 Три правила, каждое из которых закрывает свою дыру:
* владение — по подписи, а не по факту знания идентификатора;
* изоляция — подтверждается инспекцией, иначе песочница не выдаётся вовсе;
* срок жизни — принудительный: контейнер, который никто не удалил, держит память и диск
  хоста до перезапуска демона.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field

import ownership
from contracts import DEFAULT_TTL_SEC, HARD_TTL_SEC, MAX_WORKSPACES
from drivers import ComputeDriver, ContainerRef, IsolationUnverified
from policy import WorkspacePolicy

logger = logging.getLogger("workspace-sidecar.core")

# Как часто подметаем истёкшие. Реже срока жизни, но много реже — иначе «истекла» и
# «удалена» расходятся на минуты, и клиент видит живой контейнер после срока.
REAP_INTERVAL_SEC = 30.0


class WorkspaceNotFound(Exception):
    """Песочницы нет: не создавалась, истекла или уже удалена."""


class TooManyWorkspaces(Exception):
    """Достигнут общий потолок. Ресурс хостовой, потолок общий."""


@dataclass(slots=True)
class Workspace:
    workspace_id: str
    user_id: str
    ref: ContainerRef
    policy: WorkspacePolicy
    expires_at: float
    created_at: float = field(default_factory=time.time)

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at


class WorkspaceRegistry:
    """Все песочницы этого процесса. Единственный владелец драйвера."""

    def __init__(self, driver: ComputeDriver, *, max_workspaces: int = MAX_WORKSPACES) -> None:
        self._driver = driver
        self._max = max_workspaces
        self._items: dict[str, Workspace] = {}
        # ⚠️ Брони — ОТДЕЛЬНЫМ множеством, а не заглушкой в словаре песочниц: заглушка
        # заставляла бы каждого читателя помнить, что значение может быть не песочницей.
        self._reserved: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def driver_name(self) -> str:
        return getattr(self._driver, "name", "unknown")

    def count(self) -> int:
        """Занятые места, включая брони: бронь держит ресурс так же, как готовая песочница."""
        return len(self._items) + len(self._reserved)

    async def create(
        self, user_id: str, policy: WorkspacePolicy, ttl_sec: float = DEFAULT_TTL_SEC
    ) -> tuple[Workspace, str]:
        """Создать песочницу и выдать токен владения.

        🔴 Изоляция проверяется ДО того, как идентификатор уедет наружу. Не подтвердилась —
        контейнер уничтожается: выдать «песочницу», про которую неизвестно, песочница ли
        она, хуже, чем не выдать ничего.
        """
        ttl = min(max(1.0, float(ttl_sec)), HARD_TTL_SEC)
        async with self._lock:
            self._drop_expired()
            if self.count() >= self._max:
                raise TooManyWorkspaces(f"песочниц уже {self.count()} при потолке {self._max}")
            workspace_id = secrets.token_hex(8)
            self._reserved.add(workspace_id)

        try:
            ref = await self._driver.create(workspace_id, policy)
        except Exception:
            async with self._lock:
                self._reserved.discard(workspace_id)
            raise

        try:
            await self._driver.verify_isolation(ref, policy)
        except IsolationUnverified:
            await self._driver.destroy(ref)
            async with self._lock:
                self._reserved.discard(workspace_id)
            raise

        item = Workspace(
            workspace_id=workspace_id,
            user_id=str(user_id),
            ref=ref,
            policy=policy,
            expires_at=time.time() + ttl,
        )
        async with self._lock:
            self._reserved.discard(workspace_id)
            self._items[workspace_id] = item
        return item, ownership.mint(workspace_id, str(user_id), ttl_sec=ttl)

    def get(self, workspace_id: str, user_id: str, token: str) -> Workspace:
        """Найти песочницу и УБЕДИТЬСЯ, что спрашивает её владелец.

        ⚠️ Порядок важен: подпись проверяется до сообщения о существовании. Иначе разница
        между «нет такой» и «не твоя» рассказывала бы чужие идентификаторы.
        """
        ownership.verify(token, str(workspace_id), str(user_id))
        item = self._items.get(str(workspace_id))
        if item is None or item.expired():
            raise WorkspaceNotFound(f"песочница {workspace_id} не найдена или истекла")
        if item.user_id != str(user_id):
            raise WorkspaceNotFound(f"песочница {workspace_id} не найдена или истекла")
        return item

    async def update_policy(self, item: Workspace, update: dict) -> WorkspacePolicy:
        """Горячая правка политики. Запертые поля отвергает сама политика."""
        item.policy = item.policy.with_update(update)
        return item.policy

    async def destroy(self, workspace_id: str) -> None:
        async with self._lock:
            item = self._items.pop(str(workspace_id), None)
        if item is None:
            raise WorkspaceNotFound(f"песочница {workspace_id} не найдена")
        await self._driver.destroy(item.ref)

    async def exec(self, item: Workspace, command: str):
        return await self._driver.exec(
            item.ref,
            command,
            timeout_sec=item.policy.exec_timeout_sec,
            max_output_chars=item.policy.max_output_chars,
        )

    def _drop_expired(self) -> list[Workspace]:
        now = time.time()
        expired = [w for w in list(self._items.values()) if w.expired(now)]
        for item in expired:
            self._items.pop(item.workspace_id, None)
        return expired

    async def reap(self) -> int:
        """Удалить истёкшие. Возвращает сколько — по этому числу видно, работает ли уборка."""
        async with self._lock:
            expired = self._drop_expired()
        for item in expired:
            try:
                await self._driver.destroy(item.ref)
            except Exception:  # noqa: BLE001 — одна неудача не должна останавливать уборку
                logger.exception("не удалось удалить истёкшую песочницу %s", item.workspace_id)
        if expired:
            logger.info("уборка: удалено песочниц по сроку — %d", len(expired))
        return len(expired)

    async def reap_forever(self, interval_sec: float = REAP_INTERVAL_SEC) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await self.reap()
            except Exception:  # noqa: BLE001 — уборщик обязан пережить свою ошибку
                logger.exception("цикл уборки упал, продолжаем")
