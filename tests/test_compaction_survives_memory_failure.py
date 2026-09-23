"""Сжатие истории не зависит от того, удалось ли извлечь факты в память.

Это два разных дела: память копит факты о человеке, компактизация держит размер промпта.
Они стояли в ОДНОМ `try`, и компактизация шла второй — значит любой сбой первой (MemOS
недоступен, LLM-вызов извлечения упал) молча отменял сжатие. Там же был ранний `return`
при неразрешённом memory-пользователе — тот же эффект, ещё тише.

🔴 ЦЕНА СВЯЗИ — ДЕНЬГИ, И ОНА НАКОПИТЕЛЬНАЯ. Несжатая история едет в КАЖДОМ последующем
ходе треда и оплачивается человеком как входные токены. Порог сжатия — 12 сообщений, то
есть длинный диалог без саммери дорожает с каждым ходом.

⚠️ Замером в живом стеке компактизация подтверждена рабочей (саммери строится, факт из
первого хода доживает до одиннадцатого). Здесь закрывается не сегодняшняя поломка, а
молчаливая связь, из-за которой она наступила бы при первом же сбое памяти.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import chat_worker_tasks as cwt


class _Session:
    async def commit(self):
        return None


@pytest.fixture
def calls(monkeypatch):
    """Считает, что было позвано, и даёт сломать извлечение фактов."""
    seen: dict = {}

    async def _resolve(**kw):
        return seen.get("memory_user", "u-1")

    async def _compact(**kw):
        seen["compacted"] = kw.get("thread_id")

    monkeypatch.setattr(cwt, "_resolve_memory_user_id", _resolve)
    monkeypatch.setattr(cwt, "_maybe_compact_thread", _compact)
    return seen


async def _run():
    await cwt._extract_and_charge_memory(
        pg_connector=object(),
        session=_Session(),
        redis_client=object(),
        config=object(),
        user_id="u-1",
        thread_id="t-1",
        job_id="job-1",
        user_text="привет",
    )


@pytest.mark.asyncio
async def test_compaction_runs_even_if_memory_extraction_explodes(calls, monkeypatch):
    """🔴 ГЛАВНОЕ. Извлечение фактов падает — сжатие всё равно происходит."""

    class _Boom:
        async def extract_and_save_facts(self, *a, **kw):
            raise RuntimeError("MemOS недоступен")

    monkeypatch.setattr(
        "service.services.analytics.application.memory_service.MemoryService", lambda: _Boom()
    )

    await _run()

    assert calls.get("compacted") == "t-1", "сбой памяти снова отменил сжатие истории"


@pytest.mark.asyncio
async def test_compaction_runs_even_without_a_memory_user(calls, monkeypatch):
    """🔴 ТИХИЙ ПУТЬ ТОГО ЖЕ. Memory-пользователь не разрешился — блок памяти выходит
    РАННИМ `return`, без единой записи в логе. Сжатие к памяти отношения не имеет."""
    calls["memory_user"] = None

    await _run()

    assert calls.get("compacted") == "t-1", "ранний выход блока памяти снова уносит сжатие"


@pytest.mark.asyncio
async def test_a_failing_compaction_does_not_break_the_turn(calls, monkeypatch):
    """⚠️ И наоборот: сжатие best-effort. Его сбой не должен всплывать наверх — ход уже
    отдан человеку, ронять там нечего."""

    async def _boom(**kw):
        raise RuntimeError("redis лёг")

    monkeypatch.setattr(cwt, "_maybe_compact_thread", _boom)

    await _run()  # не должно бросить


def test_the_two_steps_live_in_separate_try_blocks():
    """🔴 ТОЧКА, КОТОРУЮ ЛЕГКО ОТКАТИТЬ ОБРАТНО. Правило держится не на поведении одного
    вызова, а на СТРУКТУРЕ: сжатие обязано быть в своём `try`, иначе оно снова окажется
    под общим `except` памяти и замолчит.

    Разбираем ДЕРЕВО: подстрока «try» нашлась бы и в комментарии.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import memory_maintenance

    tree = ast.parse(inspect.getsource(memory_maintenance.extract_and_charge_memory).strip())
    tries = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]

    owning = [
        t
        for t in tries
        if any(
            isinstance(n, ast.Call) and getattr(n.func, "id", "") == "compact_thread"
            for n in ast.walk(t)
        )
    ]
    assert owning, "сжатие вне защиты — его сбой уронит хвост хода"

    # 🔴 И этот `try` НЕ ТОТ ЖЕ, что у извлечения фактов: иначе связь вернулась.
    for t in owning:
        assert not any(
            isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "extract_and_save_facts"
            for n in ast.walk(t)
        ), "сжатие снова в одном блоке с памятью — сбой памяти опять его отменит"
