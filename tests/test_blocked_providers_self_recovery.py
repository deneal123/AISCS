"""Заблокированный провайдер обязан уметь вернуться САМ.

🔴 ЖИВОЙ СТЕК. Из пяти провайдеров работали двое: mws, openai и openrouter числились
заблокированными. Причина не в них — периодическая самопроверка не работала НИ РАЗУ:

    Failed to recheck blocked providers: проба провайдера выполняется сайдкаром
    NotImplementedError: проба провайдера выполняется сайдкаром (GET /providers/health)

`_probe_one_provider` осталась заглушкой после переноса проб в сайдкар и безусловно
возводила `NotImplementedError`. Задача падала на ПЕРВОМ же заблокированном — каждые пять
минут, молча (celery считал её «успешной», записав ошибку в результат). А блокировка
persistent, и это ЕДИНСТВЕННЫЙ автоматический путь обратно: провайдер, моргнувший
однажды, оставался выключенным до ручного «Проверить» в админке.

⚠️ Второй инвариант, не менее важный: проба на стороне сайдкара — это НАСТОЯЩИЙ вызов к
провайдеру (`chat.completions.create`). Спрашивать про всех каждые пять минут значит
вернуть пуллинг, который убирали намеренно. Поэтому самопроверка обязана называть
заблокированных ПОИМЁННО.
"""

from __future__ import annotations

import pytest

from service.services.admin.application import admin_service as admin_mod
from service.services.admin.application.admin_service import AdminService


@pytest.fixture
def policy(monkeypatch):
    """Подменяем хранилище политики: кто заблокирован и кого разблокировали."""
    state = {"blocked": {"mws", "openai"}, "cleared": []}

    class _Policy:
        @staticmethod
        async def blocked_providers(*args, **kwargs):
            return set(state["blocked"])

        @staticmethod
        async def clear_blocked(name):
            state["cleared"].append(name)
            state["blocked"].discard(name)

    import service.infrastructure.provider_policy_store as store

    monkeypatch.setattr(store, "blocked_providers", _Policy.blocked_providers)
    monkeypatch.setattr(store, "clear_blocked", _Policy.clear_blocked)
    return state


@pytest.fixture
def sidecar(monkeypatch):
    """Подменяем сайдкар: запоминаем, о ком спросили, и чем ответили."""
    calls: list[dict] = []
    reply: dict = {"data": None}

    async def _fetch(config, *, force_probe=False, only=None):
        calls.append({"force": force_probe, "only": list(only) if only is not None else None})
        return reply["data"]

    import service.infrastructure.agents_client.sidecar_providers as sp

    monkeypatch.setattr(sp, "fetch_provider_health", _fetch)
    return calls, reply


def _service():
    return AdminService(admin_repo=object(), app_settings_repo=object())


@pytest.mark.asyncio
async def test_recovered_provider_is_unblocked(policy, sidecar):
    """⚠️ ГЛАВНОЕ. Снова доступный провайдер разблокируется без участия человека."""
    calls, reply = sidecar
    reply["data"] = {
        "providers": {
            "mws": {"configured": True, "reachable": True},
            "openai": {"configured": True, "reachable": False, "error": "429"},
        }
    }

    out = await _service().recheck_blocked_providers()

    assert out["cleared"] == ["mws"], f"ожившего провайдера не вернули в строй: {out}"
    assert policy["cleared"] == ["mws"]
    assert "openai" in policy["blocked"], "разблокировали того, кто по-прежнему недоступен"


@pytest.mark.asyncio
async def test_only_blocked_are_probed(policy, sidecar):
    """⚠️ Спрашиваем ПОИМЁННО про заблокированных, а не форсируем обход всех.

    Проба — настоящий вызов к провайдеру; полный обход раз в пять минут это тот самый
    пуллинг, от которого уходили (здоровье всех считается по кнопке в админке).
    """
    calls, reply = sidecar
    reply["data"] = {"providers": {}}

    await _service().recheck_blocked_providers()

    assert len(calls) == 1, f"сайдкар опрошен {len(calls)} раз вместо одного"
    assert calls[0]["only"] is not None, (
        "запрошено здоровье ВСЕХ провайдеров — периодическая задача превратилась в "
        "пуллинг с настоящими вызовами к каждому провайдеру"
    )
    assert sorted(calls[0]["only"]) == ["mws", "openai"], (
        f"спросили не про заблокированных: {calls[0]['only']}"
    )
    assert calls[0]["force"] is True, (
        "без force сайдкар ответит из breaker'а, а заблокированный трафика не видит — "
        "его выздоровление не заметит никто"
    )


@pytest.mark.asyncio
async def test_nothing_blocked_costs_nothing(sidecar, monkeypatch):
    """Никто не заблокирован → сайдкар не тревожим вовсе (и провайдеров тоже)."""
    calls, reply = sidecar

    async def _none(*args, **kwargs):
        return set()

    import service.infrastructure.provider_policy_store as store

    monkeypatch.setattr(store, "blocked_providers", _none)

    out = await _service().recheck_blocked_providers()

    assert out == {"checked": [], "cleared": []}
    assert calls == [], "сходили в сайдкар, хотя блокировок нет"


@pytest.mark.asyncio
async def test_silent_sidecar_is_not_a_verdict(policy, sidecar):
    """⚠️ Сайдкар не ответил — это НЕ «проверили, никто не ожил».

    Иначе поломка связи выглядит как успешная проверка, и разница между «провайдеры
    мертвы» и «мы их не спросили» теряется — ровно так и жил прежний баг: задача падала,
    но выглядела отработавшей.
    """
    calls, reply = sidecar
    reply["data"] = None

    out = await _service().recheck_blocked_providers()

    assert out["cleared"] == []
    assert out.get("unavailable") is True, (
        f"недоступность сайдкара неотличима от «проверили, никто не ожил»: {out}"
    )


def test_probe_stub_is_gone():
    """⚠️ Заглушки `_probe_one_provider` больше нет.

    Она возводила NotImplementedError безусловно — любой вернувшийся к ней вызов снова
    убьёт автоматическое восстановление, и снова молча.
    """
    assert not hasattr(AdminService, "_probe_one_provider"), (
        "вернулась заглушка пробы: самопроверка заблокированных опять умрёт на первом же"
    )
    import inspect

    src = inspect.getsource(admin_mod.AdminService.recheck_blocked_providers)
    assert "raise NotImplementedError" not in src, (
        "самопроверка снова возводит NotImplementedError — она падала так каждые 5 минут"
    )
