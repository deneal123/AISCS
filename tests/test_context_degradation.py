"""Деградация сборки контекста ВИДНА, а не проглатывается.

Общая беда всех случаев ниже: наблюдаемое следствие у них одинаковое и безобидное на
вид — документ приезжает модели короче, чем мог бы. Отличить «сжали как задумано» от
«сжатие упало и мы обрезали по хвосту», от «половина кусков потерялась», от «окно
модели мы вообще не знаем и считали по дефолту» было НЕЧЕМ: ни лога, ни отметки.

Поэтому каждый исход помечается — в ``as_meta()`` для трейса и warning'ом для логов.
"""

from __future__ import annotations

import logging

import pytest

from service.domain.pipeline import context_assembler as ca
from service.domain.pipeline import context_budget as cb
from service.domain.pipeline.context_budget import ContextBudget
from service.settings import config


def _budget(usable=1000, sections=None, window_known=True):
    return ContextBudget(
        window=8000,
        usable=usable,
        output_reserve=0,
        prompt_overhead=0,
        sections=sections or {"files": 400, "memory": 400},
        window_known=window_known,
    )


async def _assemble(monkeypatch, *, budget=None, compressor=None, user_input="вопрос", **kw):
    async def _fake_budget(**_kw):
        return budget or _budget()

    monkeypatch.setattr(ca, "compute_budget", _fake_budget)
    return await ca.assemble_context(
        model_id="m1", config=config, user_input=user_input, compressor=compressor, **kw
    )


@pytest.mark.asyncio
async def test_compression_failure_is_reported(monkeypatch, caplog):
    """Упавшее сжатие: отметка в трейсе + warning, а не молчаливая обрезка."""

    async def _boom(_raw, _target, _kind):
        raise RuntimeError("провайдер недоступен")

    with caplog.at_level(logging.WARNING):
        assembled = await _assemble(monkeypatch, compressor=_boom, files="документ " * 3000)

    assert "files:compress_failed" in assembled.degraded
    assert assembled.as_meta()["degraded"] == ["files:compress_failed"]
    assert any("context compression unavailable" in r.message for r in caplog.records), (
        "сбой не попал в логи"
    )


@pytest.mark.asyncio
async def test_empty_compression_result_is_reported(monkeypatch):
    """Сжиматель вернул пустоту (все куски упали) — это тоже деградация."""

    async def _empty(_raw, _target, _kind):
        return ""

    assembled = await _assemble(monkeypatch, compressor=_empty, files="документ " * 3000)

    assert "files:compress_empty" in assembled.degraded


@pytest.mark.asyncio
async def test_oversized_compression_result_is_reported(monkeypatch):
    """Сжали, но в бюджет всё равно не влезло → будет обрезка, и это надо знать."""

    async def _fat(_raw, _target, _kind):
        return "всё ещё огромный пересказ " * 3000

    assembled = await _assemble(monkeypatch, compressor=_fat, files="документ " * 3000)

    assert "files:compress_useless" in assembled.degraded


@pytest.mark.asyncio
async def test_successful_compression_reports_nothing(monkeypatch):
    """⚠️ Штатный день — пустой список.

    Без этого теста можно было бы помечать деградацию ВСЕГДА, и остальные тесты этого
    не заметили бы: они проверяют только наличие отметки.
    """

    async def _ok(_raw, _target, _kind):
        return "короткая выжимка"

    assembled = await _assemble(monkeypatch, compressor=_ok, files="документ " * 3000)

    assert assembled.degraded == []
    assert "degraded" not in assembled.as_meta()


@pytest.mark.asyncio
async def test_unknown_window_is_reported(monkeypatch):
    """Окно модели неизвестно — бюджет посчитан вслепую, и это видно в трейсе."""
    assembled = await _assemble(monkeypatch, budget=_budget(window_known=False), files="документ")

    assert assembled.as_meta()["window_known"] is False


@pytest.mark.asyncio
async def test_known_window_does_not_clutter_meta(monkeypatch):
    """А когда всё известно — лишнего поля в метаданных каждого ответа нет."""
    assembled = await _assemble(monkeypatch, files="документ")

    assert "window_known" not in assembled.as_meta()


@pytest.mark.asyncio
async def test_giant_input_drops_context_instead_of_padding_it(monkeypatch, caplog):
    """Реплика больше всего бюджета: секции выброшены целиком, а не обрезаны в труху.

    Раньше каждая секция обрезалась до одного символа и всё равно рендерилась вместе с
    заголовком — в заведомо переполненный промпт мы ДОБАВЛЯЛИ разметку.
    """
    with caplog.at_level(logging.WARNING):
        assembled = await _assemble(
            monkeypatch,
            budget=_budget(usable=200),
            user_input="очень длинный вопрос " * 300,
            files="документ " * 500,
            memory="память " * 500,
        )

    assert assembled.system_context == "", "в переполненный промпт всё ещё что-то добавлено"
    assert sorted(assembled.degraded) == ["files:no_room_for_context", "memory:no_room_for_context"]
    assert any("не оставляет места контексту" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_unknown_window_falls_back_to_default_and_warns(monkeypatch, caplog):
    """resolve_window: пустой каталог → дефолт + warning + known=False."""

    async def _empty_catalog():
        return {}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _empty_catalog)

    with caplog.at_level(logging.WARNING):
        window, known = await cb.resolve_window("совершенно-неизвестная/модель", config)

    assert known is False
    assert window == int(cb._flag(config, "context_default_window", 32768))
    assert any("Окно модели" in r.message for r in caplog.records), "деградация молчала"


@pytest.mark.asyncio
async def test_known_window_is_marked_known(monkeypatch):
    """А известная модель отмечается как известная — иначе флаг был бы бесполезен."""

    async def _catalog():
        return {"acme/big": {"context_window": 1_000_000, "capabilities": [], "name": "big"}}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)

    window, known = await cb.resolve_window("acme/big", config)

    assert known is True
    assert window == 1_000_000
