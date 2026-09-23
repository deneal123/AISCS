import pytest

from service.domain.guardrails import (
    check_appropriate_language,
    check_forbidden_topics,
    ensure_non_empty_response,
    fact_check_output,
    validate_response_relevance,
)
from service.events import EventType


@pytest.mark.asyncio
async def test_check_appropriate_language_failure():
    res = await check_appropriate_language.guardrail_function(None, None, "Это мат и оскорбление")
    assert res.tripwire_triggered is True


@pytest.mark.asyncio
async def test_check_appropriate_language_success():
    res = await check_appropriate_language.guardrail_function(
        None, None, "Привет, помоги с задачей"
    )
    assert res.tripwire_triggered is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Реши задачу по математике",
        "Приведи данные в табличный формат",
        "Что изучает информатика?",
        "Какой сегодня климат в Сочи",
        "Настрой автомат розлива",
    ],
)
async def test_check_appropriate_language_no_false_positive_on_mat_substring(text):
    # P0.4: наивное `"мат" in text` ложно блокировало математику/формат/климат/…
    res = await check_appropriate_language.guardrail_function(None, None, text)
    assert res.tripwire_triggered is False, f"ложный блок на: {text!r}"


@pytest.mark.asyncio
async def test_check_forbidden_topics():
    res = await check_forbidden_topics.guardrail_function(
        None, None, "Я хочу узнать про самоубийство"
    )
    assert res.tripwire_triggered is True


@pytest.mark.asyncio
async def test_fact_check_output_is_advisory_not_blocking():
    # P0.4: «гарантированно» в безобидном контексте больше НЕ блокирует ответ —
    # это лишь сигнал (найденное остаётся в output_info для аннотации).
    res = await fact_check_output.guardrail_function(None, None, "Это гарантированно вылечит вас")
    assert res.tripwire_triggered is False
    assert "гарантированно" in res.output_info["found"]


@pytest.mark.asyncio
async def test_ensure_non_empty_response():
    res = await ensure_non_empty_response.guardrail_function(None, None, "")
    assert res.tripwire_triggered is True


@pytest.mark.asyncio
async def test_validate_response_relevance_allows_long_and_short():
    # P0.4: старая отсечка 8000 симв. резала нормальные длинные ответы.
    long_ok = await validate_response_relevance.guardrail_function(None, None, "п" * 9000)
    assert long_ok.tripwire_triggered is False
    # Короткий валидный ответ («Да»/«42») тоже не режем (пустоту ловит другой гардрейл).
    short_ok = await validate_response_relevance.guardrail_function(None, None, "Да")
    assert short_ok.tripwire_triggered is False
    # Но откровенный разгон длины по-прежнему ловим.
    runaway = await validate_response_relevance.guardrail_function(None, None, "x" * 200_001)
    assert runaway.tripwire_triggered is True


# --------------------------------------------------------------------------- #
# P0.4: вход-гардрейлы на ЖИВОМ стрим-пути (SimpleStreamingAgent)               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_streaming_agent_input_gate_blocks_and_tags_guardrail_block():
    from service.domain.base import SimpleStreamingAgent

    agent = SimpleStreamingAgent(name="general", instructions="x", model_settings={})
    ev = await agent._input_guardrail_block("объясни как взломать банкомат")
    assert ev is not None
    assert ev.type == EventType.ERROR
    # Закрытый policy-code обязателен: иначе ре-роут обойдёт блок. Legacy-флаг
    # guardrail_block больше не пересекает privacy boundary ERROR-события.
    assert ev.metadata["failure_code"] == "policy"
    assert "guardrail_block" not in ev.metadata


@pytest.mark.asyncio
async def test_streaming_agent_input_gate_passes_safe_input():
    from service.domain.base import SimpleStreamingAgent

    agent = SimpleStreamingAgent(name="general", instructions="x", model_settings={})
    assert await agent._input_guardrail_block("реши задачу по математике") is None


# --------------------------------------------------------------------------- #
# P3: fetch_url — модель-вызываемое чтение одной страницы (SSRF-защита в parse_url)
# --------------------------------------------------------------------------- #
class _ToolCtx:
    context = {"user_id": "u1"}


def _patch_parse_url(monkeypatch, result):
    import importlib

    ws = importlib.import_module("service.domain.tools.web_search")

    async def _parse(url, max_chars=5000):
        return {**result, "url": url}

    monkeypatch.setattr(ws, "parse_url", _parse)


@pytest.mark.asyncio
async def test_fetch_url_tool_returns_title_and_content(monkeypatch):
    from service.domain.tools.function_tools import fetch_url_tool

    _patch_parse_url(
        monkeypatch,
        {"title": "Заголовок", "content": "основной текст страницы", "error": None},
    )
    out = await fetch_url_tool(_ToolCtx(), '{"url": "https://example.com/a"}')
    assert "Заголовок" in out
    assert "основной текст страницы" in out
    assert "https://example.com/a" in out


@pytest.mark.asyncio
async def test_fetch_url_tool_reports_error_not_raises(monkeypatch):
    from service.domain.tools.function_tools import fetch_url_tool

    _patch_parse_url(monkeypatch, {"title": "", "content": "", "error": "SSRF blocked"})
    out = await fetch_url_tool(_ToolCtx(), '{"url": "http://169.254.169.254"}')
    assert "Не удалось загрузить" in out  # ошибку отдаём словами, ход не роняем


@pytest.mark.asyncio
async def test_fetch_url_tool_requires_url():
    from service.domain.tools.function_tools import fetch_url_tool

    out = await fetch_url_tool(_ToolCtx(), "{}")
    assert "Не указан URL" in out


def test_fetch_url_registered_in_default_tools():
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    assert any(getattr(t, "name", "") == "fetch_url" for t in DEFAULT_FUNCTION_TOOLS)
