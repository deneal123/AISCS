"""Молчаливая потеря: гардрейл выключился, файлы не доехали.

Оба случая объединяет то же свойство, что и остальные находки этой фазы: наружу они
выглядят как штатная работа, и отличить их не по чему.

* **Гардрейл входа.** Сбой САМОЙ проверки означал «блокировки нет». Fail-open здесь
  правильный — сломанный гардрейл не должен класть сервис, — но уровень был DEBUG, то
  есть на типовом INFO ни одной записи. Это единственное место, где вход-фильтр вообще
  применяется на живом стрим-пути.

* **Табличные файлы для DuckDB.** Файл больше лимита и остаток списка после исчерпания
  суммарного бюджета отбрасывались БЕЗ единой строки лога — при том что двумя строками
  выше сетевые сбои логировались. Модель делает SQL по подмножеству таблиц и уверенно
  отвечает по неполным данным; ни события, ни метки, ни лога.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime

import pytest

from service.domain.subagents.general import GeneralAgent
from service.domain.tools import duckdb_client
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


# --------------------------------------------------------------------------- #
# Гардрейл входа                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_broken_guardrail_is_loud_but_still_fail_open(monkeypatch, caplog):
    """⚠️ Фильтр выключился — пропускаем запрос, но не молча."""
    import service.domain.guardrails as guards

    async def _boom(ctx, agent, text):
        raise RuntimeError("гардрейл сломан")

    monkeypatch.setattr(guards.check_appropriate_language, "guardrail_function", _boom)

    agent = GeneralAgent({"model": "test-model"})
    with caplog.at_level(logging.WARNING):
        blocked = await agent._input_guardrail_block("любой текст")

    assert blocked is None, "fail-open сохранён: сломанный гардрейл не кладёт сервис"
    assert any("input guardrail failed code=internal" in r.message for r in caplog.records), (
        "фильтр безопасности отключился беззвучно — неотличимо от штатного «пропускаю»"
    )


@pytest.mark.asyncio
async def test_working_guardrail_stays_quiet(caplog):
    """Штатный пропуск молчит — иначе предупреждение станет фоновым шумом."""
    agent = GeneralAgent({"model": "test-model"})

    with caplog.at_level(logging.WARNING):
        assert await agent._input_guardrail_block("как приготовить омлет") is None

    assert not caplog.records


# --------------------------------------------------------------------------- #
# Табличные файлы DuckDB                                                        #
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, content: bytes):
        self.status_code = 200
        self.content = content


@pytest.fixture
def served(monkeypatch):
    """Отдаём по ссылке заданное содержимое."""

    def _serve(payload: bytes):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                return _Resp(payload)

        monkeypatch.setattr(duckdb_client.httpx, "AsyncClient", lambda **kw: _Client())

    return _serve


@pytest.mark.asyncio
async def test_oversized_file_drop_is_logged(served, caplog):
    """⚠️ Файл больше лимита выбрасывался без лога — ответ по неполным данным."""
    served(b"x" * (duckdb_client.MAX_FILE_BYTES + 1))

    with caplog.at_level(logging.WARNING):
        out, skipped = await duckdb_client.fetch_tabular_files_from_urls(
            [{"url": "http://x/big.csv", "name": "big.csv"}]
        )

    assert out == [], "поведение прежнее: слишком большой файл в анализ не идёт"
    assert any("big.csv" in n for n in skipped), "пропуск не отдан наружу для модели"
    assert any(
        "duckdb source exceeds size limit code=invalid" in r.message for r in caplog.records
    ), (
        "файл выброшен молча — модель ответит по подмножеству таблиц, и связать это "
        "с потерей будет нечем"
    )
    assert all("big.csv" not in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_file_within_limits_is_taken_quietly(served, caplog):
    """Контроль предпосылки: нормальный файл проходит и не шумит."""
    served(b"a,b\n1,2\n")

    with caplog.at_level(logging.WARNING):
        out, skipped = await duckdb_client.fetch_tabular_files_from_urls(
            [{"url": "http://x/ok.csv", "name": "ok.csv"}]
        )

    assert len(out) == 1 and skipped == []
    assert base64.b64decode(out[0]["content_b64"]) == b"a,b\n1,2\n"
    assert not caplog.records
