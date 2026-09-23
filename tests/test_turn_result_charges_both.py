"""Фиксация результата хода: списаний ДВА, и оба попадают в счёт и в метаданные.

🔴 ЭТОТ УЗЕЛ БЫЛ ВЫНЕСЕН И НЕ СТЕРЁГСЯ НИЧЕМ. Мутации показали это прямо: «usage роутера
больше не списывается», «возвращается только основное списание», «метаданные стоимости не
собираются», «воркер не зовёт фиксацию результата» — ВСЕ ЧЕТЫРЕ прошли зелёными. Тесты
рядом проверяли `_charge_usage` в одиночку, а обёртку, которая соединяет два списания и
собирает стоимость для человека, — никто.

Цена каждого правила — деньги:
* потеря списания за роутер = его токены сгорают мимо биллинга (платформа платит, в счёт не
  попадает);
* заниженная сумма = реституция при сбое вернёт БОЛЬШЕ, чем сняли, и напечатает кредиты;
* потерянные метаданные = человек не видит, за что заплатил.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure.chat_worker import turn_result


@pytest.fixture
def charges(monkeypatch):
    """Подменяет оба списания: считаем, что и сколько было позвано."""
    calls: dict[str, int] = {}

    async def main(**kw):
        calls["main"] = 1
        return 700

    async def router(**kw):
        calls["router"] = 1
        return 30

    monkeypatch.setattr(turn_result, "_charge_usage", main)
    monkeypatch.setattr(turn_result, "_charge_router_usage", router)
    return calls


async def _run(metadata=None, usage_meta=("stub",)):
    return await turn_result.charge_and_describe(
        pg_connector=object(),
        redis_client=None,
        config=object(),
        execution_result={"total_tokens": 100},
        session_data={"_router_usage": {"total": 10}},
        metadata=dict(metadata or {"kind": "reply"}),
        thread_id="t-1",
        job_id="job-1",
        user_id="u-1",
        resolved_model="openai/gpt-4o",
        selected_model="auto",
        reservation_id="r-1",
        reserved_estimate=500,
        started_at=0.0,
    )


@pytest.mark.asyncio
async def test_both_charges_are_summed(charges, monkeypatch):
    """🔴 ГЛАВНОЕ. 700 за ответ + 30 за роутер = 730. Потеря второго = токены мимо биллинга,
    заниженная сумма = реституция вернёт больше, чем сняли."""
    monkeypatch.setattr(turn_result, "build_public_usage_meta", lambda *a, **k: {"credits": 730})

    charged, _ = await _run()

    assert charges == {"main": 1, "router": 1}, "одно из двух списаний не позвано"
    assert charged == 730, f"сумма списаний потеряна: {charged}"


@pytest.mark.asyncio
async def test_usage_meta_reaches_metadata(charges, monkeypatch):
    """⚠️ Стоимость видит ЧЕЛОВЕК: без блока `usage` интерфейс не покажет, за что списано."""
    monkeypatch.setattr(
        turn_result, "build_public_usage_meta", lambda *a, **k: {"credits": 730, "model": "m"}
    )

    _, metadata = await _run({"kind": "reply"})

    assert metadata["usage"] == {"credits": 730, "model": "m"}
    assert metadata["kind"] == "reply", "прежние метаданные затёрты"


@pytest.mark.asyncio
async def test_empty_usage_meta_is_not_written(charges, monkeypatch):
    """🔴 ГРАНИЦА. `usage: {}` в интерфейсе читается как «ход бесплатный» — а это другое:
    не собралось и не стоило. Пустой блок не кладём вовсе."""
    monkeypatch.setattr(turn_result, "build_public_usage_meta", lambda *a, **k: None)

    _, metadata = await _run({"kind": "reply"})

    assert "usage" not in metadata


@pytest.mark.asyncio
async def test_the_meta_is_built_after_both_charges(charges, monkeypatch):
    """⚠️ ПОРЯДОК НЕСУЩИЙ: собери метаданные до второго списания — и человек увидит
    стоимость МЕНЬШЕ фактической."""
    seen: dict = {}

    def meta(execution_result, **kw):
        seen["credits"] = kw.get("charged_credits")
        return {"credits": kw.get("charged_credits")}

    monkeypatch.setattr(turn_result, "build_public_usage_meta", meta)

    await _run()

    assert seen["credits"] == 730, "метаданные собраны до того, как учтён роутер"


def test_the_worker_delegates_to_this_node():
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а воркер считает сам — и они разойдутся.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым вынос объяснён.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import run_execution

    tree = ast.parse(inspect.getsource(run_execution._finalize_success).strip())
    used = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "charge_and_describe"
    ]

    assert used, "воркер не зовёт фиксацию результата — списания и стоимость разъедутся"
