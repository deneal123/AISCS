"""Стражи сайдкара: владение, запертая политика, ПОДТВЕРЖДЁННАЯ изоляция.

Всё, что здесь проверяется, — правила, снятие которых даёт доступ к чужим данным или к
хосту. Docker не нужен: драйвер подменяется, а разбор инспекции проверяется на словаре —
именно так и выглядит ответ демона.
"""

from __future__ import annotations

import asyncio
import pathlib
import time

import pytest

import ownership
from core import TooManyWorkspaces, WorkspaceNotFound, WorkspaceRegistry
from drivers.base import ContainerRef, IsolationUnverified
from drivers.docker_cli import _create_argv, _isolation_complaints
from policy import StaticPolicyLocked, WorkspacePolicy, policy_from_request

SECRET = "0123456789abcdef-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", SECRET)


# --- токен владения ----------------------------------------------------------------


def test_owner_token_round_trips() -> None:
    token = ownership.mint("ws1", "user-7")
    ownership.verify(token, "ws1", "user-7")


def test_token_of_another_workspace_is_refused() -> None:
    """🔴 Иначе угаданный идентификатор = доступ к чужой файловой системе."""
    token = ownership.mint("ws1", "user-7")
    with pytest.raises(ownership.OwnershipError):
        ownership.verify(token, "ws2", "user-7")


def test_token_of_another_user_is_refused() -> None:
    token = ownership.mint("ws1", "user-7")
    with pytest.raises(ownership.OwnershipError):
        ownership.verify(token, "ws1", "user-8")


def test_expired_token_is_refused() -> None:
    """⚠️ Подпись НАСТОЯЩАЯ, просрочен только срок.

    Подделанный срок при старой подписи отвергался бы проверкой ПОДПИСИ, и снятие проверки
    срока не покраснело бы ничем — тест смотрел бы не на то правило.
    """
    expires_at = int(time.time()) - 10
    stale = f"{expires_at}.{ownership._sign('ws1', 'user-7', expires_at)}"
    with pytest.raises(ownership.OwnershipError):
        ownership.verify(stale, "ws1", "user-7")


def test_signature_is_compared_in_constant_time() -> None:
    """Правило, которое НЕЛЬЗЯ проверить поведением: `==` и `compare_digest` дают один и тот
    же ответ и различаются только временем. Разница видна лишь тому, кто подбирает подпись
    побайтово, — то есть измеримо только атакой. Поэтому страж смотрит на ИСХОДНИК: это
    честнее, чем зелёный тест, ничего не гарантирующий."""
    source = pathlib.Path(ownership.__file__).read_text(encoding="utf-8")
    assert "hmac.compare_digest(expected, signature)" in source
    assert "expected == signature" not in source
    assert "expected != signature" not in source


def test_forged_signature_is_refused() -> None:
    token = ownership.mint("ws1", "user-7")
    expires, _, _ = token.partition(".")
    with pytest.raises(ownership.OwnershipError):
        ownership.verify(f"{expires}.{'0' * 64}", "ws1", "user-7")


def test_service_refuses_to_work_without_a_secret(monkeypatch) -> None:
    """⚠️ Дефолтный ключ = подпись, которую умеет ставить кто угодно."""
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "short")
    with pytest.raises(RuntimeError):
        ownership.mint("ws1", "user-7")


# --- политика: статическая половина заперта -----------------------------------------


@pytest.mark.parametrize("field", ["network", "read_only_root", "image", "quota_bytes", "user"])
def test_static_fields_cannot_be_changed_on_a_live_workspace(field: str) -> None:
    """🔴 Право, доехавшее до работающего контейнера, — повышение привилегий по расписанию."""
    policy = WorkspacePolicy()
    with pytest.raises(StaticPolicyLocked):
        policy.with_update({field: "bridge" if field in ("network", "image", "user") else 1})


def test_dynamic_fields_can_be_changed() -> None:
    policy = WorkspacePolicy().with_update({"exec_timeout_sec": 42.0})
    assert policy.exec_timeout_sec == 42.0


def test_locked_field_refuses_the_whole_update() -> None:
    """Частичное применение оставило бы песочницу в состоянии, которого не просил никто."""
    policy = WorkspacePolicy()
    with pytest.raises(StaticPolicyLocked):
        policy.with_update({"exec_timeout_sec": 42.0, "network": "bridge"})
    assert policy.exec_timeout_sec != 42.0


def test_unknown_policy_field_is_an_error_not_a_silent_skip() -> None:
    """⚠️ Молча пропущенное поле политики = вызывающий думает, что ограничение применено."""
    with pytest.raises(ValueError):
        policy_from_request({"netwrok": "none"})


def test_exec_timeout_above_the_hard_cap_is_refused() -> None:
    with pytest.raises(ValueError):
        WorkspacePolicy(exec_timeout_sec=10**6)


# --- изоляция ПОДТВЕРЖДАЕТСЯ, а не заявляется ---------------------------------------


def _inspect(**overrides) -> dict:
    host = {
        "NetworkMode": "none",
        "Privileged": False,
        "CapAdd": None,
        "ReadonlyRootfs": True,
        "Memory": 512 * 1024 * 1024,
        "PidsLimit": 256,
    }
    host.update(overrides)
    return {"HostConfig": host}


def test_correct_container_passes_verification() -> None:
    assert _isolation_complaints(_inspect(), WorkspacePolicy()) == []


@pytest.mark.parametrize(
    "override",
    [
        {"NetworkMode": "bridge"},
        {"Privileged": True},
        {"CapAdd": ["SYS_ADMIN"]},
        {"ReadonlyRootfs": False},
        {"Memory": 0},
        {"PidsLimit": 0},
    ],
)
def test_every_deviation_is_reported(override: dict) -> None:
    """Каждое отклонение — отдельная жалоба: «песочница» без одного флага не песочница."""
    assert _isolation_complaints(_inspect(**override), WorkspacePolicy())


def test_create_argv_carries_every_restriction() -> None:
    """Флаги здесь — ограничения, а не настройки; пропажа любого молча ослабляет песочницу."""
    argv = " ".join(_create_argv("ws1", WorkspacePolicy()))
    assert "--network none" in argv
    assert "no-new-privileges" in argv
    assert "--cap-drop ALL" in argv
    assert "--read-only" in argv
    assert "--pids-limit" in argv
    # ⚠️ Без своп-лимита потолок памяти обходится свопом.
    assert "--memory-swap" in argv


# --- реестр -------------------------------------------------------------------------


class _FakeDriver:
    name = "fake"

    def __init__(self, *, verified: bool = True) -> None:
        self.verified = verified
        self.created: list[str] = []
        self.destroyed: list[str] = []

    async def create(self, workspace_id, policy):
        self.created.append(workspace_id)
        # ⚠️ Настоящее создание контейнера идёт СЕКУНДЫ. Без явной уступки управления
        # корутины не перемежаются, гонки за место не возникает — и тест на бронь зеленеет
        # даже без самой брони.
        await asyncio.sleep(0)
        return ContainerRef(self.name, f"c-{workspace_id}")

    async def verify_isolation(self, ref, policy):
        if not self.verified:
            raise IsolationUnverified("сеть контейнера 'bridge'")

    async def exec(self, ref, command, *, timeout_sec, max_output_chars):
        raise AssertionError("не должно вызываться в этих тестах")

    async def destroy(self, ref):
        self.destroyed.append(ref.container_id)


async def test_unverified_isolation_destroys_the_container_and_hands_out_nothing() -> None:
    """🔴 Выдать «песочницу», про которую неизвестно, песочница ли она, хуже, чем не выдать."""
    driver = _FakeDriver(verified=False)
    registry = WorkspaceRegistry(driver)
    with pytest.raises(IsolationUnverified):
        await registry.create("user-7", WorkspacePolicy())
    assert driver.destroyed, "контейнер остался жить после неподтверждённой изоляции"
    assert registry.count() == 0


async def test_owner_token_is_required_to_reach_a_workspace() -> None:
    registry = WorkspaceRegistry(_FakeDriver())
    item, token = await registry.create("user-7", WorkspacePolicy())
    registry.get(item.workspace_id, "user-7", token)
    with pytest.raises(ownership.OwnershipError):
        registry.get(item.workspace_id, "user-8", token)


async def test_expired_workspace_is_not_returned() -> None:
    registry = WorkspaceRegistry(_FakeDriver())
    item, token = await registry.create("user-7", WorkspacePolicy(), ttl_sec=1)
    item.expires_at = time.time() - 1
    with pytest.raises(WorkspaceNotFound):
        registry.get(item.workspace_id, "user-7", token)


async def test_reaper_destroys_expired_containers() -> None:
    """⚠️ Контейнер, который никто не удалил, держит память хоста до перезапуска демона."""
    driver = _FakeDriver()
    registry = WorkspaceRegistry(driver)
    item, _ = await registry.create("user-7", WorkspacePolicy())
    item.expires_at = time.time() - 1
    assert await registry.reap() == 1
    assert driver.destroyed == [item.ref.container_id]


async def test_total_cap_is_enforced() -> None:
    registry = WorkspaceRegistry(_FakeDriver(), max_workspaces=1)
    await registry.create("user-7", WorkspacePolicy())
    with pytest.raises(TooManyWorkspaces):
        await registry.create("user-8", WorkspacePolicy())


async def test_place_is_reserved_before_the_slow_driver_call() -> None:
    """⚠️ Без брони параллельные запросы пробили бы потолок все разом."""
    registry = WorkspaceRegistry(_FakeDriver(), max_workspaces=2)
    results = await asyncio.gather(
        *(registry.create(f"user-{i}", WorkspacePolicy()) for i in range(4)),
        return_exceptions=True,
    )
    refused = [r for r in results if isinstance(r, TooManyWorkspaces)]
    assert len(refused) == 2 and registry.count() == 2


def test_unknown_driver_is_an_error_not_a_silent_docker() -> None:
    """⚠️ Фолбэк на умолчание дал бы рантайм слабее заказанного, и узнать было бы неоткуда."""
    from drivers import build_driver

    with pytest.raises(ValueError):
        build_driver("firecracker")


# --- таймаут: путь, который тесты не видели, а живой прогон сломал ------------------


class _GoneProcess:
    """Процесс `docker exec`, который завершился САМ, пока мы добивали группу внутри."""

    returncode = None

    async def communicate(self):
        await asyncio.sleep(10)  # никогда не успеет: вызывающий ждёт с таймаутом

    def kill(self):
        raise ProcessLookupError("процесса уже нет")

    async def wait(self):
        raise ProcessLookupError("процесса уже нет")


async def test_timeout_returns_a_result_even_if_the_exec_process_is_already_gone(
    monkeypatch,
) -> None:
    """🔴 Таймаут отдавал 500 БЕЗ результата: клиент не получал ни вывода, ни признака.

    Добивание группы внутри контейнера завершает хостовой `docker exec` раньше нас, и
    `proc.kill()` бросал ProcessLookupError. Живой дефект; тесты его не видели, потому что
    подменяли драйвер целиком — здесь подменяется только ЗАПУСК ПРОЦЕССА.
    """
    from drivers.docker_cli import DockerCliDriver

    driver = DockerCliDriver()

    async def fake_exec(*args, **kwargs):
        return _GoneProcess()

    async def no_kill(ref):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(driver, "_kill_process_group", no_kill)

    result = await driver.exec(
        ContainerRef("docker", "c1"), "sleep 60", timeout_sec=0.05, max_output_chars=100
    )
    assert result.timed_out is True
    assert result.exit_code == -1, "таймаут обязан быть отличим от успешного завершения"
