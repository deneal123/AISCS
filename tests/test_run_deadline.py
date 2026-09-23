"""У прогона `/run` есть общий дедлайн.

⚠️ Его не было ВОВСЕ. `run_timeout_sec` был объявлен в настройках и не читался нигде, а
единственной верхней границей оставался таймаут httpx конкретного провайдера — который
умножается на число ретраев (`llm_retry_attempts`) и на длину цепочки фейловера и ничем
не ограничен сверху. Мета-вызовы (декомпозиция, оценка сложности, план, сжатие контекста)
шли вообще без `wait_for`. Провайдер, держащий соединение открытым и не отдающий дельт,
удерживал задачу столько, сколько готов ждать backend, — то есть 10 минут.

## Почему дефолт поднят с 90 до 570 секунд

Настройка не действовала, значит её значение никогда не проверялось реальностью. Deep
research идёт через тот же `/run`, и один только опрос LDR бюджетирует 240 с
(`ldr_timeout_sec`) — включение «как объявлено» убивало бы его на 90-й секунде. 570
даёт время deep research. Backend ждёт этот же deadline вместе с recovery grace, поэтому
частичный result успевает доехать вместо оборванного соединения.
"""

from __future__ import annotations

import asyncio

import pytest

from service.presentation.routers.agent import run as run_mod


@pytest.fixture
def deadline(monkeypatch):
    """Задать дедлайн так, как его увидит прогон (через overlay админки)."""

    def _set(value):
        from service.shared.agent_settings import runtime_settings

        monkeypatch.setattr(
            runtime_settings,
            "get_agents",
            lambda name, default=None: value if name == "run_timeout_sec" else default,
        )

    return _set


def test_deadline_comes_from_the_admin_overlay(deadline):
    """⚠️ Через overlay, а не напрямую из конфига — иначе тумблер не действует.

    Ровно эта ошибка в сервисе уже встречалась дважды (потолок синтеза, основной
    эмбеддер): значение читалось из конфига, админка его меняла, и ничего не менялось.
    """
    deadline(42.5)
    assert run_mod._run_deadline_sec() == 42.5


def test_default_leaves_room_for_deep_research():
    """⚠️ Дефолт обязан переживать LDR: у него одного бюджет 240 с.

    Backend derives its own transport timeout from this value with recovery grace,
    so the sidecar deadline remains the first finalization boundary.
    """
    from service.settings import config

    value = float(config.agents.run_timeout_sec)

    assert value > 240, f"дедлайн {value} с убьёт deep research (его бюджет 240 с)"


@pytest.mark.parametrize("value", [0, -1, 0.0], ids=["ноль", "отрицательный", "ноль-дробью"])
def test_zero_means_no_deadline_not_instant_death(deadline, value):
    """⚠️ Ноль — это «выключено», а НЕ «мгновенный таймаут».

    `asyncio.wait_for(coro, timeout=0)` срабатывает немедленно: верни функция ноль
    вместо None, аварийный выключатель убивал бы КАЖДЫЙ прогон. Это тот случай, когда
    отключение защиты опаснее самой защиты.
    """
    deadline(value)
    assert run_mod._run_deadline_sec() is None


def test_garbage_falls_back_to_config(deadline):
    """Мусор в overlay (строка из БД) не должен ронять ручку."""
    deadline("не число")
    from service.settings import config

    assert run_mod._run_deadline_sec() == float(config.agents.run_timeout_sec)


@pytest.mark.asyncio
async def test_none_deadline_does_not_time_out():
    """Контроль семантики `wait_for`: с None он ждёт, с 0 — падает сразу.

    Проверяется поведение библиотеки, на которое опирается предыдущий тест, — чтобы
    смена версии Python не сделала аварийный выключатель тихо смертельным.
    """

    async def _quick():
        return "готово"

    assert await asyncio.wait_for(_quick(), timeout=None) == "готово"

    async def _slow():
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_slow(), timeout=0)
